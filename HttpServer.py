from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import SimplePeriphDev
import json
import Controller
import time
import copy


class CustomHTTPRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        super(CustomHTTPRequestHandler, self).__init__(request, client_address, server)
        # As the client is subscribed to events for the whole session, the handler should never terminate it by itself
        self.close_connection = False

    def do_GET(self):
        if self.path == '/updates':
            # Update long-poll request
            time.sleep(5)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(bytes('XHResponse text!', self.server.encoding))
        elif self.path == '/initial_data':
            """
            Initial server data request. All the devices, their controls, current states,
            also controller controls (e.g. "Turn on automatic pump control")
            Response format example:
            {
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
        if self.path == '/command':
            print(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(bytes('Accepted', self.server.encoding))
        else:
            self.send_error(400)

    def version_string(self):
        # Why unused?
        return 'Top' + 'Sickrekt'


class CustomHTTPServer(ThreadingMixIn, HTTPServer):
    def __init__(self, server_address, main_page_file_name_template, favicon_file_name, controller: Controller):
        super(CustomHTTPServer, self).__init__(server_address, CustomHTTPRequestHandler)
        with open(favicon_file_name, 'rb') as favicon_file:
            self.favicon_data = favicon_file.read()
        self.main_page_file_name_template = main_page_file_name_template
        self.encoding = 'UTF-8'
        self.controller = controller
