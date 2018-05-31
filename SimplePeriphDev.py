import pygatt
import logging
import threading
from enum import Enum
import copy


class RaisedErrors(Enum):
    EndDeviceError = 1
    NoSuchParameter = 2


class InternalErrors(Enum):
    InvalidFormat = 1
    MaxBufferLengthExceeded = 2


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
        # Threading lock for multithreading. Locks whenever the work with the device is in progress
        self._lock = threading.Lock()
        # Function. Called when device's characteristics update
        self.parameter_updated_callback = self.default_parameter_updated_callback
        # Function. Called when the device encounters an error during its usage
        # (e.g. could not recognize command)
        self.error_callback = self.default_error_callback
        # Function. Called when the device goes offline
        self.gone_offline_callback = self.default_gone_offline_callback
        # self.parameters is not meant to be changed directly. Use self. send_command
        self._parameters = {}

        #for curr_param in self.description['parameters']:
        #    self.parameters[curr_param['name']] = None

    @property
    def parameters(self):
        raise NotImplementedError

    # Sends ASCII text to the device.
    def __send_text(self, text: str):
        raise NotImplementedError

    def default_parameter_updated_callback(self, device, parameter, value):
        logging.info('Default update callback has been called for "%s" device. %s:%s', device, parameter, value)

    def default_error_callback(self, device, code, message):
        logging.warning('Default error callback has been called for "%s" device. Message: "%s"', device, message)

    def default_gone_offline_callback(self, device):
        logging.warning('Default gone ofline callback has been called for "%s" device.', device)

    def send_command(self, parameter, value):
        """
        Tries to change a controllable parameter "parameter" to "value".
        :param parameter: Parameter to be changed
        :param value: Value to be assigned to the specified parameter
        :return:
        """
        raise NotImplementedError

    def __init_parameters(self):
        raise NotImplementedError

    def __str__(self):
        return self.description['name']


# BLE peripheral device with simple real/integer/boolean parameters and controls
# E.g. this class can be used for accessing well controller peripheral, but it is not designed for, say, video-camera
# modules peripherals
class SimpleBlePeriphDev(SimplePeriphDev):
    class Exceptions:
        class NotConnectedError(Exception):
            pass

    # BLE module serial characteristic handle is 0x025
    bleModuleSerialCharHandle = 0x025
    bleModuleSerialCharUUID = '0000ffe1-0000-1000-8000-00805f9b34fb'

    # update_handler is a function that is going to be called if the device sends a notification
    def __init__(self, description, ble_adapter, blocking_connect=False, blocking_param_init=False):
        """
        Safe for use by multiple threads, has embedded lock
        :param description:
        :param ble_adapter: pygatt Backend
        :param blocking: If True, blocks until the device's parameters are initialized.
        """
        super(SimpleBlePeriphDev, self).__init__(description)
        self.__ble_adapter = ble_adapter
        self.__conn = None
        self.online = threading.Event()
        self.__connect(blocking=blocking_connect)
        # A buffer to write messages from device to
        self.__message_buffer = ''
        # An event which is set to one when device's parameters have been initialized
        self.parameters_initialized = threading.Event()
        self.__init_parameters(blocking=blocking_param_init)

    @property
    def parameters(self):
        """
        Returns a copy of self.__parameters
        Not all parameters may be initialized
        :return:
        """
        with self._lock:
            return copy.deepcopy(self._parameters)

    def send_command(self, parameter, command):
        # Let's check if we need to transfer any text or the parameter is already in the requested parameters
        logging.info("To %s command %s:%s", self, parameter, command)
        with self._lock:
            skip = self._parameters.get(parameter, None) == command
        if skip:
            pass
        else:
            try:
                self.__send_text('PRM:{}:{}'.format(parameter, command))
            except self.exceptions.NotConnectedError:
                logging.error('Attempted to send a command to the disonnected device %s', self)

    # Sends ASCII text to the device. text cannot be an empty string
    def __send_text(self, text: str):
        """
        Sends ASCII text to the BLE device. Protocol:
        :param text:
        :return:
        """
        # ';' is a termination symbol
        if self.online.is_set():
            try:
                self.__conn.char_write(uuid=self.bleModuleSerialCharUUID,
                                       value=str.encode(text + ';', encoding='ASCII'),
                                       wait_for_response=True)
                logging.debug('To dev {} sent "{}"'.format(self, text))
            except pygatt.exceptions.NotConnectedError:
                self.__handle_not_connected()
        else:
            # Raise or handle?
            raise self.Exceptions.NotConnectedError

    def __handle_notification(self, handle, raw_data):
        """
        Called by pygatt when a BLE device sends a notification. Therefore it is not possible that this method is called
        by multiple threads (if it is used right). If the device sends a long message, this method will be called
        multiple times consequently and the message is going to be transmitted by parts.
        Threrefore we're using end of transmission symbol - ';'. Also we're using self.__notification_buffer

        :param handle:
        :param raw_data:
        :return:
        """
        max_buffer_length = 256
        # Consider locking less code <efficiency>
        raw_string = raw_data.decode('ASCII')
        logging.info('PeriphDev %s notif raw: "%s"', self, raw_string)
        curr_message_start = 0
        while curr_message_start < len(raw_string):
            terminal_pos = raw_string.find('.', curr_message_start)
            if terminal_pos == -1:
                # No message end found. Buffering
                # Check whether max buffer length is exceeded
                if len(self.__message_buffer) + len(raw_string) > max_buffer_length:
                    self.internal_error_handler(InternalErrors.MaxBufferLengthExceeded,
                                                'Maximum buffer length exceeded')
                    return
                self.__message_buffer += raw_string[curr_message_start:]
                # Stop processing this string
                break
            else:
                # Found a message termianal symbol
                self.__handle_message(self.__message_buffer + raw_string[curr_message_start:terminal_pos])
                # Omitting terminal symbol
                curr_message_start = terminal_pos + 1
                self.__message_buffer = ''

    def __handle_message(self, message: str):
        """
        Called by __handle_notification (it cannot happen that this method is used by multiple threads (if it is used
        right).
        Parses the received message and performs corresponding actions.
        This method can only be called by one thread
        Acceptable "message" format:
        <notification_type>[:<arguments>]
        <notification_type> can be: "PRM" or "ERR"
        "PRM" is used to transfer information about parameter updates
        if the <notification_type> is "PRM", <arguments> must have the following format:
        <param>:<val>
        Examples:
        PRM:well_water_presence:not_present
        :param message:
        :return:
        """
        logging.info('From %s message %s', self, message)
        split_data = message.split(':')
        if len(split_data) < 2:
            self.internal_error_handler(InternalErrors.InvalidFormat,
                                        'Invalid format: "' + message + '"')
        else:
            if split_data[0] == 'PRM':
                if len(split_data) != 3:
                    self.internal_error_handler(InternalErrors.InvalidFormat,
                                                'Invalid message format: "{}"'.format(message))
                else:
                    # Check if specified parameter exists
                    for curr_param_description in self.description['parameters']:
                        if curr_param_description['name'] == split_data[1]:
                            # Parameter found
                            # Perform actions according to parameter type
                            parameter_name = split_data[1]
                            if curr_param_description['type'] == 'bool':
                                # Boolean parameter's value can only be one of two strings described in 'states'
                                # attribute
                                if (split_data[2] == curr_param_description['states'][0]) or \
                                        (split_data[2] == curr_param_description['states'][1]):
                                    # Parameter value is valid
                                    parameter_value = split_data[2]
                                else:
                                    # Parameter value is invalid. Handling the error, exiting
                                    self.internal_error_handler(InternalErrors.InvalidFormat,
                                                                'Invalid parameter value: "' + message + '"')
                                    return
                            elif curr_param_description['type'] == 'float':
                                # Try parsing received value into float
                                try:
                                    parameter_value = float(split_data[2])
                                    # Parameter value is valid
                                except ValueError:
                                    # Parameter value is invalid. Handling the error, exiting
                                    self.internal_error_handler(InternalErrors.InvalidFormat,
                                                                'Invalid message format: "{}"'.format(message))
                                    return
                            else:
                                raise NotImplementedError('Parameter format "{}" is not supported'.
                                                          format(curr_param_description['type']))
                            # Everything's alright, changing self.parameters, calling parameter_updated_callback
                            with self._lock:
                                self._parameters[parameter_name] = parameter_value
                            # If the device is not initialized yet, check if all parameters are added, set the device to
                            # initialized, if true. Branch predictor should help CPU omit this when it is initialized
                            if not self.parameters_initialized.is_set():
                                for curr_param in self.description['parameters']:
                                    if curr_param['name'] not in self._parameters:
                                        # Found a parameter that is still not initialized
                                        break
                                else:
                                    # No uninitialized parameters found
                                    self.parameters_initialized.set()
                                    logging.info("Device {} 's parameters have been initialized".format(self))
                            self.parameter_updated_callback(device=self, parameter=parameter_name,
                                                            value=parameter_value)
                            # Stop searching for parameter, it's found already
                            break
                    else:
                        # No such parameter
                        self.internal_error_handler(InternalErrors.InvalidFormat,
                                                    'No such parameter: "{}"'.format(message))
            elif split_data[0] == 'ERR':
                self.error_callback(device=self, code=RaisedErrors.EndDeviceError, message=message)
            else:
                self.internal_error_handler(InternalErrors.InvalidFormat, 'Invalid message type: "' + message + '"')

    def __handle_not_connected(self):
        # If online has already been set to False, that means that we're already trying to reconnect
        if self.online.is_set():
            logging.warning('Device {} has gone offline. Trying to reconnect'.format(self))
            with self._lock:
                self.online.clear()
                self.__connect(blocking=False)
            self.gone_offline_callback(self)

    def internal_error_handler(self, code, message):
        logging.error('Device "{}": an internal error has occurred: {}'.format(self, message))

    def __request_state_when_comes_online(self):
        """
        Designed to be called by __init_parameters. Blocks until 'STATE' message is sent to the device
        :return:
        """
        success = False
        while not success:
            self.online.wait()
            try:
                self.__send_text('STATE')
                success = True
            except self.Exceptions.NotConnectedError:
                self.__handle_not_connected()

    def __init_parameters(self, blocking=True):
        """
        Tells the BLE device to send information about each of its characteristics' state
        :param blocking: if True, blocks until all the parameters are initialized,
        :return:
        """
        # Request is sent only when device comes online
        if not blocking:
            thread = threading.Thread(target=self.__request_state_when_comes_online, daemon=True)
            thread.start()
        else:
            self.__request_state_when_comes_online()
            # 'Initialized' event will be set in the notification handler
            self.parameters_initialized.wait()


    def __connect_no_timeout(self):
        """
        This function is used by self.__connect method to continuously try to connect to the BLE device
        :return:
        """
        # Connecting with no timeout (well, technically with 3-year timeout but with subseqent retry)
        new_connection = None
        while new_connection is None:
            try:
                new_connection = self.__ble_adapter.connect(self.description['MAC'], 99999999)
                new_connection.subscribe(uuid=self.bleModuleSerialCharUUID, callback=self.__handle_notification,
                                      indication=True)
            except pygatt.exceptions.NotConnectedError:
                pass

        logging.info('%s connected', self)
        with self._lock:
            self.online.set()
            self.__conn = new_connection


    def __connect(self, blocking):
        """
        Continuously tries to reconnect to the device
        :param blocking: If true, blocks until connected.
        :return:
        """
        if not blocking:
            # Creating another thread
            thread = threading.Thread(target=self.__connect_no_timeout, daemon=True)
            thread.start()
        else:
            self.__connect_no_timeout()

    def __str__(self):
        return self.description['name']

    def __repr__(self):
        if self.online.is_set():
            return '{} MAC: {}\tonline'.format(self.description['name'], self.description['MAC'])
        else:
            return '{} MAC: {}\toffline'.format(self.description['name'], self.description['MAC'])
