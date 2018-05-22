from threading import Lock
import copy
from typing import Dict
from SimplePeriphDev import SimpleBlePeriphDev, SimplePeriphDev
import json


class Controller:
    """
    This class may be used by multiple threads (in our case - by HTTP server and peripheral devices)
    """

    def __init__(self, periph_devices: Dict[str, SimplePeriphDev], periph_devices_descriptions,
                 controller_config_file_name: str):
        # self.config_file_name = controller_config_file_name
        self.periph_devices = periph_devices
        self.pump_dev = self.periph_devices['well_and_tank']
        # Telling devices to send notification to this controller then requesting their states
        # Their responses will be handled in a different function
        for curr_dev in self.periph_devices.values():
            curr_dev.notification_handler = self.handle_device_notification
        self.config_lock = Lock()
        # Initialize config variable.
        # Mutex could be used here. But no need in it - it's an __init__ function, which means nothing can access an
        # instance of this class before __init__ is finished
        self.config = {}
        # Reading config data
        with open(controller_config_file_name) as config_file:
            # Acquiring lock is not required as we're in __init__
            self.config = json.load(config_file)

    @property
    def full_state(self):
        """
        Returns a copy of the current state of all peripheral devices and controller config data structure.
        Not supposed to be be modified manually
        :return: Sample format:
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
        return_val_struct = {}
        return_val_struct['devices'] = []
        with self.config_lock:
            return_val_struct['controller_config'] = copy.deepcopy(self.config)
        for curr_dev_name, curr_dev in self.periph_devices.items():
            with curr_dev.lock:
                curr_dev_state_copy = copy.deepcopy(curr_dev.state)
            return_val_struct['devices'].append({})
            return_val_struct['devices'][-1]['name'] = curr_dev_name
            return_val_struct['devices'][-1]['parameters'] = curr_dev_state_copy
        return return_val_struct


    def handle_user_command(self, command):
        """
        Used to transfer user commands to the controller
        :param command: JSON-formatted command
        :return:
        """

    def handle_device_notification(self, device: SimplePeriphDev, parameter: str, value: str):
        """
        Handles a device notification
        :param parameter:
        :param device: Device which send that notification
        :param value: The value of the specifiend characteristic
        :return:
        """
        print('controller.handle_device_notification called')

    def handle_update(self, update):
        """
        :param update: Update JSON-formatted data (not string, JSON-like Python data structure)
        :return:
        """

    # Automation functions are followed. Consider moving logic into config-file

    def manage_pump(self):
        """
        Analyzes the current state of the system and controller config and manages pump according to it
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
                    if self.config['pump_auto_control_turn_off_when_well_empty']:
                        with self.pump_dev.lock:
                            if self.pump_dev.state['well_water_presence'] == 'not_present':
                                # No water in the well
                                self.pump_dev.send_command('pump', 'turn_off')
                            else:
                                # Water in the well is present
                                if self.config['pump_auto_control_turn_off_when_tank_full']:
                                    if self.pump_dev.state['tank'] == 'full':
                                        self.pump_dev.send_command('pump', 'turn_off')
                                    else:
                                        self.pump_dev.send_command('pump', 'turn_on')
                    else:
                        # Do not turn off the pump if the well is empty
                        with self.pump_dev.lock:
                            if self.config['pump_auto_control_turn_off_when_tank_full']:
                                if self.pump_dev.state['tank'] == 'full':
                                    self.pump_dev.send_command('pump', 'turn_off')
                                else:
                                    self.pump_dev.send_command('tank', 'turn_on')
                            else:
                                # Do not trun off the pump when the tank is full
                                self.pump_dev.send_command('pump', 'turn_on')
