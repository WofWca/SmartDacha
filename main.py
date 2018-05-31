from SimplePeriphDev import SimpleBlePeriphDev
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
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('pygatt').setLevel(logging.CRITICAL)
    # logging.disable(logging.WARNING)
    logging.logProcesses = 0

    # Reading peripheral devices' information from the configuration file
    with open(periph_devices_descriptions_filename) as periphDevDescrFile:
        periph_devices_descriptions = json.load(periphDevDescrFile)

    # Forming the main page from template
    template = Template(open(main_page_template_file_name).read())
    curr_locale = 'en'
    open('{}_{}.html'.format(main_page_file_name_template, curr_locale), 'w').write(template.render(
        {'periph_devices_descriptions': periph_devices_descriptions,
         'locale': curr_locale}))
    curr_locale = 'ru'
    open('{}_{}.html'.format(main_page_file_name_template, curr_locale), 'w').write(template.render(
        {'periph_devices_descriptions': periph_devices_descriptions,
         'locale': curr_locale}))

    # Connecting to the peripheral devices
    # All the peripheral devices
    periph_devices = {}
    ble_adapters = []
    # Note: for some reason if there's an adapter that has been already connected to a device, starting another adapter
    # will disconnect it. First starting two adapters and connecting devices after that does not behave like that.
    # !!!Bug report?
    # creating and starting adapters
    for curr_device_descr in periph_devices_descriptions:
        if curr_device_descr['type'] == 'BLE_serial_AT-09':
            # One adapter per each BLE peripheral device (don't mix up with hci0, hci1 etc)
            curr_ble_adapter = pygatt.GATTToolBackend()
            curr_ble_adapter.start()
            ble_adapters.append(curr_ble_adapter)
    # Connecting devices to created adapters
    for i in range(0, len(ble_adapters)):
        new_ble_periph_device = SimpleBlePeriphDev(description=periph_devices_descriptions[i],
                                                   ble_adapter=ble_adapters[i])
        periph_devices[periph_devices_descriptions[i]['name']] = new_ble_periph_device

    # Controller init
    controller = Controller(periph_devices, periph_devices_descriptions, controller_config_file_name)

    # HTTP Server (individual thread)
    http_server = CustomHTTPServer(http_server_address, main_page_file_name_template, favicon_file_name, controller)
    controller.update_callback = http_server.parameter_update_handler
    http_server.user_command_callback = controller.handle_user_command
    logging.info('Running HTTP server')
    http_server.serve_forever()
    # http_server_thread = threading.Thread(target=run_http_server, daemon=False)
    # http_server_thread.start()

    # Main cycle
    # logging.info('Initialization complete')
    """
    # while True:
        # time.sleep(retry_connection_delay)
        # Retry connecting to devices that are offline
        for curr_dev in periph_devices.values():
            if curr_dev.online == False:
                connection_result = curr_dev.connect(retry_connection_tiemout)
                if connection_result == True:
                    logging.info('%s connection retry succeeded', curr_dev)
                else:
                    logging.debug('%s connection retry failed', curr_dev)
    """