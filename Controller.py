from threading import Lock
from typing import Dict
from SimplePeriphDev import SimpleBlePeriphDev, SimplePeriphDev
import json
import logging


class Controller:
    """
    self.full_state:
        Holds the current state of all peripheral devices and controller config data structure.
        Not supposed to be be modified directly.
        Do not forget to use locks - Controller's self.config_lock and devices' locks for each
        Sample format:
        {
            "devices": [
                {
                    "name": "well_and_tank",
                    "parameters":
                    {
                        'well_water_presence": 'not_present',
                        'pump': 'off',
                        'tank': 'not_full'
                    }
                },
                {
                    "name": "Greenhouse",
                    ...
                },
                ...
            ],
            "controller_config": {
                "pump_auto_control_turn_off_when_tank_full": true
            }
        }
    """

    def __init__(self, periph_devices: Dict[str, SimplePeriphDev], periph_devices_descriptions,
                 controller_config_file_name: str):
        # self.config_file_name = controller_config_file_name
        self.periph_devices = periph_devices
        self.well_tank_dev = self.periph_devices['well_and_tank']
        self.greenhouse_dev = self.periph_devices['greenhouse']
        # Telling devices to send notification to this controller then requesting their states
        # Their responses will be handled in a different function
        for curr_dev in self.periph_devices.values():
            curr_dev.parameter_updated_callback = self.handle_device_parameter_update
        # update_callback is called whenever an update happens. argument - update data with format similar to
        # self.full_state
        self.update_callback = self.__default_update_callback
        self.error_callback = self.__default_error_callback
        self.config_lock = Lock()
        # Initialize config variable.
        # Mutex could be used here. But no need in it - it's an __init__ function, which means nothing can access an
        # instance of this class before __init__ is finished
        self.config = {}
        # Reading config data
        with open(controller_config_file_name) as config_file:
            # Acquiring lock is not required as we're in __init__
            self.config = json.load(config_file)

    def handle_user_command(self, command_text):
        """
        Parses user command and executes it if it is valid
        :param command_text: raw user-formed string
        :return:
        """
        try:
            command = json.loads(command_text)
        except json.JSONDecodeError:
            self.error_callback('Could not parse user command')
            return

        target = command.get('target', None)
        parameter = command.get('parameter', None)
        command = command.get('command', None)
        if target == 'controller':
            pass
        elif target == 'well_and_tank':
            # if the pump is controlled automatically, user command has no effect
            with self.config_lock:
                is_auto = self.config['pump_auto_control']
            if is_auto:
                self.error_callback('Attempted to execute a manual command on an automated parameter')
                return
            if parameter == 'pump':
                # Find parameter description
                for curr_param in self.well_tank_dev.description['parameters']:
                    if curr_param['name'] == 'pump':
                        break
                if (command != curr_param['commands'][0]) and \
                        (command != curr_param['commands'][1]):
                    self.error_callback('Invalid value {}:{}:{}'.format(target, parameter, command))
                    return
                self.well_tank_dev.send_command(parameter, command)
                # No need to call handle_updates as there are no updates yet - the device has not confirmed that its
                # state has changed
            else:
                self.error_callback("Cannot control {}'s parameter {}".format(target, parameter))
                return

    def handle_device_parameter_update(self, device: SimplePeriphDev, parameter, value):
        """
        Called when a device's characteristic has been updated. This function will be assigned to devices'
        self.parameter_updated_callback s. In its turn, calls self.update_callback, which may be a
        HTTP server function
        :param device: Device which send that notification
        :return:
        """
        update_data = {
            'devices': [{
                'name': device.description['name'],
                'parameters': {
                    parameter: value
                }
            }],
            'controller_config': {}
        }
        self.handle_updates(update_data)
        self.update_callback(update_data)

    def handle_device_error(self, device: SimplePeriphDev):
        """
        Called when a device raises an error
        :param device: Device which send that notification
        :return:
        """
        pass

    def handle_updates(self, update):
        """
        Called when something changes its parameters (e.g. controller config or device)
        :param update: Update JSON-formatted data (not string, JSON-like Python data structure)
        :return:
        """
        self.__manage_pump()

    def __default_update_callback(self, update_data):
        logging.warning("Controller's default device parameter updated callback called")

    def __default_error_callback(self, message):
        logging.error('Default controller error callback called: "' + message + '"')

    # Automation functions are followed. Consider moving logic into config-file

    def __manage_pump(self):
        """
        Analyzes the current parameters of the system and controller config and manages pump according to it
        :return:
        """
        with self.config_lock:
            if self.config['pump_auto_control'] == False:
                # Controller doesn't need to do anything about the pump as it is in manual control mode
                pass
            else:
                # Pump is in automatic mode
                if self.config['"pump_auto_control_mode'] == 'normally_off':
                    # For current functionality there is nothing that can force the pump to turn on (e.g.
                    # fire extinguishing).
                    pass
                else:
                    # Pump is normally on.
                    pump_parameters = self.well_tank_dev.parameters
                    if self.config['pump_auto_control_turn_off_when_well_empty']:
                        if pump_parameters ['well_water_presence'] == 'not_present':
                            # No water in the well
                            self.well_tank_dev.send_command('pump', 'turn_off')
                        else:
                            # Water in the well is present
                            if self.config['pump_auto_control_turn_off_when_tank_full']:
                                if pump_parameters['tank'] == 'full':
                                    self.well_tank_dev.send_command('pump', 'turn_off')
                                else:
                                    self.well_tank_dev.send_command('pump', 'turn_on')
                    else:
                        # Do not turn off the pump if the well is empty
                        if self.config['pump_auto_control_turn_off_when_tank_full']:
                            if pump_parameters ['tank'] == 'full':
                                self.well_tank_dev.send_command('pump', 'turn_off')
                            else:
                                self.well_tank_dev.send_command('pump', 'turn_on')
                        else:
                            # Do not trun off the pump when the tank is full
                            self.well_tank_dev.send_command('pump', 'turn_on')
