from SimplePeriphDev import SimpleStubPeriphDev
import json
import logging
import time
import pygatt
import threading
from HttpServer import CustomHTTPServer
from jinja2 import Template
from Controller import Controller

# Configuration variables
retry_connection_delay = 10  # In seconds
retry_connection_tiemout = 1  # In seconds
periph_devices_descriptions_filename = 'PeriphDevicesDescriptions.json'
http_server_address = ('', 3228)
# A template for the main page file name. There will be different pages for different locales.
# Resulting name examples (for template 'index'): index_ru.html, index_en.html
# This may be inefficient
main_page_file_name_template = 'HTTPServerData/index'
# File name of the page main template
main_page_template_file_name = 'HTTPServerData/template_index.html'
favicon_file_name = 'HTTPServerData/favicon.ico'
controller_config_file_name = 'controller_config.json'


def run_http_server():
    http_server.serve_forever()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger('pygatt').setLevel(logging.CRITICAL)
    # logging.disable(logging.WARNING)
    logging.logProcesses = 0

    # Reading peripheral devices' information from the configuration file
    with open(periph_devices_descriptions_filename) as periphDevDescrFile:
        periph_devices_descriptions = json.load(periphDevDescrFile)

    # Forming the main page from template
    template = Template(open(main_page_template_file_name).read())
    curr_locale = 'ru'
    open('{}_{}.html'.format(main_page_file_name_template, curr_locale), 'w').write(template.render(
        {'periph_devices_descriptions': periph_devices_descriptions,
         'locale': curr_locale}))

    periph_devices = {
        'well_and_tank': SimpleStubPeriphDev(periph_devices_descriptions[0]),
        'greenhouse': SimpleStubPeriphDev(periph_devices_descriptions[1])
    }

    # Controller init
    controller = Controller(periph_devices, periph_devices_descriptions, controller_config_file_name)

    # HTTP Server (individual thread)
    http_server = CustomHTTPServer(http_server_address, main_page_file_name_template, favicon_file_name, controller)
    http_server_thread = threading.Thread(target=run_http_server, daemon=True)
    http_server_thread.start()
    logging.debug('HTTP server started')

    # Main cycle
    logging.debug('Running main cycle')
    while True:
        param = input('well_and_tank param:')
        val = input('well_and_tank val')
        periph_devices['well_and_tank'].imitate_notification(param, val)
        param = input('greenhouse param:')
        val = input('greenhouse val')
        periph_devices['greenhouse'].imitate_notification(param, val)
