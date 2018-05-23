import pygatt
import logging
import threading
from enum import Enum


class RaisedErrors(Enum):
    EndDeviceError = 1
    NoSuchParameter = 2


class InternalErrors(Enum):
    InvalidFormat = 1


class SimplePeriphDev:

    def __init__(self, description):
        """
        self.parameters structure sample format:
        {
            'well_water_presence": 'not_present',
            'pump': 'off',
            'tank': 'not_full'
        }
        :param description: Device description structure (see PeriphDevicesDescriptions.json)
        """
        self.description = description # Is it safe?!!!
        self.online = False
        # Threading lock for multithreading. Locks whenever the work with the device is in progress
        self.lock = threading.Lock()
        # Function. Called when device's characteristics update
        self.parameter_updated_callback = self.default_parameter_updated_callback
        # Function. Called when the device encounters an error due to incorrect use of itself
        # (e.g. could not recognize command)
        self.error_handler = self.default_error_handler
        # Function. Called when the device goes offline
        self.gone_offline_handler = self.default_error_handler
        # self.parameters is not meant to be changed directly. Use self. set_parameter
        self.parameters = {}
        # self.__init_parameters()

        #for curr_param in self.description['parameters']:
        #    self.parameters[curr_param['name']] = None

    # Sends ASCII text to the device.
    def __send_text(self, text: str):
        raise NotImplementedError

    def default_parameter_updated_callback(self, device, parameter, value):
        logging.info('Default update handler has been called for "{}" device. {}:{}'.format(device, parameter, value))

    def default_error_handler(self, device, code, message):
        logging.warning('Default error handler has been called for "{}" device. Message: "{}"'.format(device, message))

    def default_gone_offline_handler(self):
        pass

    def set_parameter(self, parameter, value):
        """
        Tries to change a controllable parameter "parameter" to "value".
        :param parameter: Parameter to be changed
        :param value: Value to be assigned to the specified parameter
        :return:
        """
        raise NotImplementedError

    def __str__(self):
        return self.online


# BLE peripheral device with simple real/integer/boolean parameters and controls
# E.g. this class can be used for accessing well controller peripheral, but it is not designed for, say, video-camera
# modules peripherals
class SimpleBlePeriphDev(SimplePeriphDev):
    # BLE module serial characteristic handle is 0x025
    bleModuleSerialCharHandle = 0x025
    bleModuleSerialCharUUID = '0000ffe1-0000-1000-8000-00805f9b34fb'

    # update_handler is a function that is going to be called if the device sends a notification
    def __init__(self, description, ble_adapter):
        super(SimpleBlePeriphDev, self).__init__(description)
        self.MAC = description['MAC']
        self.ble_adapter = ble_adapter
        self.conn = None
        self.connect()
        # A buffer to write messages from device to
        self.__notification_buffer = ''

    def set_parameter(self, parameter, value):
        # Let's check if we need to transfer any text or the parameter is already in the requested parameters
        if self.parameters[parameter] == value:
            pass
        else:
            self.__send_text('PRM:{}:{}'.format(parameter, value))

    def connect(self, timeout=5):
        """
        try connecting to the device
        :param timeout: timeout in seconds
        :return: True if connection succeeded, else False
        """
        try:
            self.conn = self.ble_adapter.connect(self.MAC, timeout)
            self.online = True
            self.conn.subscribe(uuid=self.bleModuleSerialCharUUID, callback=self.__handle_notification, indication=True)
            return True
        except pygatt.exceptions.NotConnectedError:
            return False

    # Sends ASCII text to the device. text cannot be an empty string
    def __send_text(self, text: str):
        """
        Sends ASCII text to the BLE device. Protocol:
        :param text:
        :return:
        """
        with self.lock:
            # '\r\n' is a termination symbol
            self.conn.char_write(uuid=self.bleModuleSerialCharUUID,
                                 value=str.encode(text + '\r\n', encoding='ASCII'),
                                 wait_for_response=True)
        logging.debug('To dev {} sent "{}"'.format(self, text))

    def __handle_notification(self, handle, value):
        """
        Called when a BLE device sends a notification. If the device sends a long message, this method will be called
        multiple times and the message is going to be transmitted by parts. Threrefore we're using end of transmission
        symbol - '\r\n'. Also we're using self.__notification_buffer
        accepted "value" format:
        <notification_type>[:<arguments>]
        <notification_type> can be: "PRM" or "ERR"
        "PRM" is used to transfer information about parameter updates
        if the <notification_type> is "PRM", <arguments> must have the following format:
        <param>:<val>
        Examples:
        PRM:well_water_presence:not_present
        :param handle:
        :param value:
        :return:
        """
        # Consider locking less code <efficiency>
        raw_string = value.decode('ASCII')
        logging.debug('PeriphDev {} notif raw: "{}"'.format(self, raw_string))
        # If the message doesn't end with a termination symbol
        if raw_string[-2:] != '\r\n':
            # Add the current message to the buffer and skip processing
            self.__notification_buffer += raw_string
            return
        else:
            data_string = self.__notification_buffer + raw_string[:-2]
            # Don't forget to clear the buffer
            self.__notification_buffer = ''
        # If the received notification format is OK, call the update handler, else call the error handler
        parsed_data = data_string.split(':')
        if len(parsed_data) < 2:
            self.internal_error_handler(InternalErrors.InvalidFormat,
                                        'Invalid format: "' + data_string + '"')
        else:
            if parsed_data[0] == 'PRM':
                if len(parsed_data) != 3:
                    self.internal_error_handler(InternalErrors.InvalidFormat,
                                                'Invalid message format: "{}"'.format(data_string))
                else:
                    # Check if specified parameter exists
                    for curr_param_description in self.description['parameters']:
                        if curr_param_description['name'] == parsed_data[1]:
                            # Parameter found
                            # Perform actions according to parameter type
                            if curr_param_description['type'] == 'bool':
                                # Boolean parameter's value can only be one of two strings described in 'states'
                                # attribute
                                if (parsed_data[2] == curr_param_description['states'][0]) or \
                                        (parsed_data[2] == curr_param_description['states'][1]):
                                    # Everything's alright, changing self.parameters, calling parameter_updated_callback
                                    with self.lock:
                                        self.parameters[parsed_data[1]] = parsed_data[2]
                                    self.parameter_updated_callback(device=self, parameter=parsed_data[1],
                                                                    value=parsed_data[2])
                                else:
                                    self.internal_error_handler(InternalErrors.InvalidFormat,
                                                                'Invalid parameter value: "' + data_string + '"')
                            elif curr_param_description['type'] == 'float':
                                # Try parsing received value into float
                                try:
                                    parsed_value = float(parsed_data[2])
                                    # Everything's alright, changing self.parameters, calling parameter_updated_callback
                                    with self.lock:
                                        self.parameters[parsed_data[1]] = parsed_value
                                    self.parameter_updated_callback(device=self, parameter=parsed_data[1],
                                                                    value=parsed_value)
                                except ValueError:
                                    self.internal_error_handler(InternalErrors.InvalidFormat,
                                                                'Invalid message format: "{}"'.format(data_string))
                            else:
                                raise NotImplementedError('Parameter format "{}" is not supported'.
                                                          format(curr_param_description['type']))

                            # Stop searching for parameter, it's found already
                            break
                    else:
                        # No such parameter
                        self.internal_error_handler(InternalErrors.InvalidFormat,
                                                    'No such parameter: "{}"'.format(data_string))
            elif parsed_data[0] == 'ERR':
                self.error_handler(device=self, code=RaisedErrors.EndDeviceError, message=data_string)
            else:
                self.internal_error_handler(InternalErrors.InvalidFormat, 'Invalid message type: "' + data_string + '"')

    def internal_error_handler(self, code, message):
        logging.error('Device "{}": an internal error has occurred: {}'.format(self, message))


    def __reqest_status(self):
        """
        Needed for self.parameters initialization.
        :return:
        """

    def __str__(self):
        return self.description['name']

    def __repr__(self):
        if self.online:
            return '{} MAC: {}\tonline'.format(self.description['name'], self.MAC)
        else:
            return '{} MAC: {}\toffline'.format(self.description['name'], self.MAC)


class SimpleStubPeriphDev (SimplePeriphDev):

    def __init__(self, description=None):
        super(SimpleStubPeriphDev, self).__init__(description)
        for param in description['parameters']:
            self.parameters[param['name']] = param['name'] + '_stub_val'

    def __send_text(self, text: str):
        logging.warning('Stub device "{}" just got "{}"'.format(self, text))

    def imitate_notification(self, message: str):
        self.parameter_updated_callback(device=self, message=message)

class SimpleStubPeriphDev_well_and_tank (SimpleStubPeriphDev):
    def __init__(self, description):
        super(SimpleStubPeriphDev_well_and_tank, self).__init__(description)
        pass
