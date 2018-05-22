import pygatt
import logging
import threading


class SimplePeriphDev:

    def __init__(self, description):
        """

        self.state structure sample format:
        {
            'well_water_presence": 'not_present',
            'pump': 'off',
            'tank': 'not_full'
        }
        :param description: Device description structure (see PeriphDevicesDescriptions.json)
        """
        self.name = description['name']
        # self.description = description
        self.online = False
        # Threading lock for multithreading. Locks whenever the work with the device is in progress
        self.lock = threading.Lock()
        self.notification_handler = self.default_notification_handler
        self.state = {}

    # Sends ASCII text to the device.
    def __send_text(self, text: str):
        raise NotImplementedError

    def default_notification_handler(self, device, parameter, value):
        logging.info('Default notification handler called for device "{}".'
        'Parameter: "{}", Value: "{}"'.format(device, parameter, value))

    def send_command(self, parameter, value):
        """
        Should only be used to change controllable parameters. Validation is performed on the end device
        To get device's full status use self.__request_status
        :param parameter: Parameter to be changed
        :param value: Value to be assigned to the specified parameter
        :return:
        """
        # Let's check if we need to transfer any text or the parameter is already in the requested state
        if self.state[parameter] == value:
            self.__send_text('{}:{}'.format(parameter, value))

    def __reqest_status(self):
        """
        Needed for self.state initialization
        :return:
        """

    def __str__(self):
        return self.online


# BLE peripheral device with simple real/integer/boolean parameters and controls
# E.g. this class can be used for accessing well controller peripheral, but it is not designed for, say, video-camera
# modules peripherals
class SimpleBlePeriphDev(SimplePeriphDev):
    # BLE module serial characteristic handle is 0x025
    bleModuleSerialCharHandle = 0x025
    bleModuleSerialCharUUID = '0000ffe1-0000-1000-8000-00805f9b34fb'

    # notification_handler is a function that is going to be called if the device sends a notification
    def __init__(self, description, ble_adapter):
        super(SimpleBlePeriphDev, self).__init__(description)
        self.notification_handler = self.default_notification_handler
        self.MAC = description['MAC']
        self.ble_adapter = ble_adapter
        self.conn = None
        self.connect()

    def connect(self, timeout=5):
        """
        try connecting to the device
        :param timeout: timeout in seconds
        :return: True if connection succeeded, else False
        """
        try:
            self.conn = self.ble_adapter.connect(self.MAC, timeout)
            self.online = True
            self.conn.subscribe(uuid=self.bleModuleSerialCharUUID, callback=self.handle_notification, indication=True)
            return True
        except pygatt.exceptions.NotConnectedError:
            return False

    # Sends ASCII text to the device. text cannot be an empty string
    def __send_text(self, text: str):
        with self.lock:
            self.conn.char_write(uuid=self.bleModuleSerialCharUUID,
                                 value=str.encode(text, encoding='ASCII'),
                                 wait_for_response=False)
        logging.debug('To dev {} sent "{}"'.format(self, text))

    def handle_notification(self, handle, value):
        # Consider locking less code <efficiency>
        stringified_data = value.decode('ASCII')
        logging.debug('PeriphDev {} notif raw: "{}"'.format(self, stringified_data))
        separation_pos = stringified_data.find(':')
        # If the received notification's format is OK, call the notification handler, else log an error
        if separation_pos == -1:
            logging.error('Incorrect format. No ":". Device {} sent "{}"'.format(self, stringified_data))
        elif separation_pos == 0:
            logging.error('Incorrect format. Parameter name is empty. '
                          'Device {} sent "{}"'.format(self, stringified_data))
        elif separation_pos == len(stringified_data) + 1:
            logging.error('Incorrect format. New parameter value is empty.'
                          'Device {} sent: "{}"'.format(self, stringified_data))
        else:
            parameter_name = stringified_data[:separation_pos]
            parameter_value = stringified_data[separation_pos + 1:]
            self.notification_handler(device=self, parameter=parameter_name, value=parameter_value)

    def __str__(self):
        return self.name

    def __repr__(self):
        if self.online:
            return '{} MAC: {}\tonline'.format(self.name, self.MAC)
        else:
            return '{} MAC: {}\toffline'.format(self.name, self.MAC)


class SimpleStubPeriphDev (SimplePeriphDev):

    def __init__(self, description=None):
        super(SimpleStubPeriphDev, self).__init__(description)
        for param in description['parameters']:
            self.state[param['name']] = param['name'] + '_stub_val'

    def __send_text(self, text: str):
        logging.warning('Stub device "{}" just got "{}"'.format(self, text))

    def imitate_notification(self, parameter: str, value: str):
        self.notification_handler(device=self, parameter=parameter, value=value)

class SimpleStubPeriphDev_well_and_tank (SimpleStubPeriphDev):
    def __init__(self, description):
        super(SimpleStubPeriphDev_well_and_tank, self).__init__(description)
        pass
