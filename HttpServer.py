from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from threading import Event, Lock
import logging
import json
import Controller
import copy
import time
from collections import deque


class CustomHTTPServer(ThreadingMixIn, HTTPServer):
    """

    updates_buffer
        's purpose is to store the most recent updates for the case when the client has  missed some die to
        e.g. connection problems. If this happened, on the next update request all the missed updates will be packed
        into one packet and tranfsered to the client.
    """
    def __init__(self, server_address, main_page_file_name_template, favicon_file_name, controller: Controller):
        super(CustomHTTPServer, self).__init__(server_address, CustomHTTPRequestHandler)
        with open(favicon_file_name, 'rb') as favicon_file:
            self.favicon_data = favicon_file.read()
        self.main_page_file_name_template = main_page_file_name_template
        self.encoding = 'UTF-8'
        self.controller = controller
        self.device_parameter_updated_event = Event()
        self.updates_buffer_lock = Lock()
        self.updates_buffer = deque(maxlen=10)
        self.last_update_time = 0.0
        self.user_command_callback = self.default_user_command_callback

    def parameter_update_handler(self, update_data):
        self.last_update_time = time.time()
        update_data['time'] = self.last_update_time
        with self.updates_buffer_lock:
            self.updates_buffer.append(update_data)
            # Do not worry about instant clear, all the waiting threads will be awaken
        self.device_parameter_updated_event.set()
        self.device_parameter_updated_event.clear()

    def default_user_command_callback(self, target, parameter, command):
        logging.warning('Default user command callback handler called')


class CustomHTTPRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server: CustomHTTPServer):
        super(CustomHTTPRequestHandler, self).__init__(request, client_address, server)
        # As the client is subscribed to events for the whole session, the handler should never terminate it by itself
        self.close_connection = False
        self.server = server

    def do_GET(self):

        if self.path == '/initial_data':
            """
            Initial server data request. All the devices, their controls, current states,
            also controller controls (e.g. "Turn on automatic pump control")
            Response format example:
            {
                "time": 12345454.545323
                "devices": [
                    {
                        "name": "well_and_tank",
                        "parameters":
                        {
                            'well_water_presence": 'not_present',
                            'pump': 'off',
                            'tank': 'not_full'
                        },
                        "online": true
                    },
                    {
                        "name": "greenhouse",
                        "parameters":
                        {
                            'temperature": 21.1,
                            'pump': 'off',
                            'tank': 'not_full'
                        }
                        "online": false
                    },
                    ...
                ],
                "controller_config": {
                    "pump_auto_control_turn_off_when_tank_full": true
                }
            }
            """
            self.send_response(200)
            self.end_headers()
            # Forming full state data structure. It will be then stringified and sent to the client.
            state_copy = {
                'time': self.server.last_update_time,
                'devices': []
            }
            # Reading controller config
            # Not forgetting to use locks
            with self.server.controller.config_lock:
                state_copy['controller_config'] = copy.deepcopy(self.server.controller.config)
            # Reading devices' information
            for curr_dev_name, curr_dev in self.server.controller.periph_devices.items():
                with curr_dev.lock:
                    state_copy['devices'].append({
                        'name': curr_dev_name,
                        'online': curr_dev.online,
                        'parameters': copy.deepcopy(curr_dev.parameters)
                    })
            # Stingifying gathered data and sending it to the client
            self.wfile.write(bytes(json.dumps(state_copy, indent='\t'), self.server.encoding))
        elif self.path == '/favicon.ico':
            # Favicon request
            self.send_response(200)
            self.end_headers()
            self.wfile.write(self.server.favicon_data)
        else:
            # Main page request.
            self.path = '/'
            self.send_response(200)
            self.end_headers()
            # Get requested locale or set to 'en' as default
            locale = self.headers.get('Accept-Language', 'en')[0:2]
            # Try opening the corresponding file
            try:
                main_page_data = open('{}_{}.html'.format(self.server.main_page_file_name_template, locale)).read()
            except IOError:
                # Could not open the localized page file. using default
                main_page_data = open('{}_{}.html'.format(self.server.main_page_file_name_template, 'en')).read()
            self.wfile.write(bytes(main_page_data, self.server.encoding))

    def do_POST(self):
        if self.path == '/updates':
            # Update long-poll request
            # Read last update time
            try:
                client_last_update_time = float(self.rfile.read(int(self.headers['Content-Length'])))
            except:
                # Incorrect format
                self.send_error(400)
            # If the client did not receive the latest update yet
            self.server.updates_buffer_lock.acquire()
            # noinspection PyUnboundLocalVariable
            if self.server.last_update_time > client_last_update_time:
                self.send_response(200)
                self.end_headers()
                # Forming update data.
                # Find the earliest unreceived update. Starting from the end. More likely to find it at the end
                for curr_update in reversed(self.server.updates_buffer):
                    if curr_update['time'] > client_last_update_time:
                        # Found one.
                        update_to_send = curr_update
                        break
                self.server.updates_buffer_lock.release()
            else:
                # Client's up to date. Waiting for new updates
                self.server.updates_buffer_lock.release()
                self.server.device_parameter_updated_event.wait()
                # A brand new update's at the end of update deque
                self.send_response(200)
                self.end_headers()
                with self.server.updates_buffer_lock:
                    update_to_send = self.server.updates_buffer[-1]
            self.wfile.write(bytes(json.dumps(update_to_send), self.server.encoding))
        elif self.path == '/command':
            self.server.user_command_callback(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(bytes('Command transferred', self.server.encoding))
        else:
            self.send_error(400)

    def version_string(self):
        # Why unused?
        return 'Top' + 'Sickrekt'

