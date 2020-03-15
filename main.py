#!/usr/bin/env python3

import threading
import I2C_LCD_driver
import logging
import time
import sys
import os
import json
import paho.mqtt.client as mqtt
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

http_port=8080
mqtt_host="pi1.iot"
mqtt_port=1883

fontIcons = [
    [0x0e,0x1b,0x11,0x04,0x0a,0x00,0x04,0x00],
    [0x01,0x03,0x05,0x09,0x09,0x0b,0x1b,0x18],
    [0x00,0x08,0x0C,0x0E,0x0F,0x0E,0x0C,0x08],
    [0x00,0x00,0x00,0x00,0x00,0x1b,0x1b,0x00],
    [0x04,0x0A,0x0A,0x0A,0x0A,0x11,0x11,0x0E],
    [0x00,0x15,0x0E,0x1B,0x0E,0x15,0x00,0x00],
    [0x00,0x0E,0x1F,0x0E,0x1F,0x0E,0x1F,0x00]
]

mappingIcons = {
    "wifi": 0,
    "music": 1,
    "play": 2,
    "dots": 3,
    "temp": 4,
    "cpu": 5,
    "ram": 6
}

mappingChars = {
    "deg":  chr(0b11011111),
    "fill": chr(0b11111111)
}

formatter = logging.Formatter('%(asctime)s|%(name)s|%(levelname)s:\t%(message)s')
logger = logging.getLogger('i2c_web')
logger.setLevel(logging.DEBUG)

fileHandler = logging.FileHandler('/var/log/i2c.log')
fileHandler.setLevel(logging.DEBUG)
fileHandler.setFormatter(formatter)
logger.addHandler(fileHandler)

#console output
consoleHandler = logging.StreamHandler()
consoleHandler.setLevel(logging.DEBUG)
consoleHandler.setFormatter(formatter)
logger.addHandler(consoleHandler)

class LoggerWriter:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, message):
        if message != '\n':
            self.logger.log(self.level, message)

sys.stdout = LoggerWriter(logger, logging.INFO)
sys.stderr = LoggerWriter(logger, logging.ERROR)

def replaceIcon(line):
    arr = line.split('|')
    leng = len(arr)
    if (leng == 1):
        return line
    else:
        for idx, val in enumerate(arr):
            if val in mappingIcons:
                arr[idx] = chr(mappingIcons[val])
            if val in mappingChars:
                arr[idx] = mappingChars[val]
        return ''.join(arr)

class LCDPrinter:
    def __init__(self):
        self.lcd = I2C_LCD_driver.lcd()
        self.processing = False
        self.queue = []
        queue = threading.Thread(name='queue', target=self.run)
        logger.info("starting queue")
        queue.start()
        bootup = threading.Thread(name='bootled', target=self.startup)
        bootup.start()

    def startup(self):
        l = chr(0b11111111)
        self.lcd.backlight(1)
        self.lcd.lcd_display_string(f' {l} {l} Daemon {l} {l} ')
        self.lcd.lcd_display_string(f'{l} {l} {l}  up  {l} {l} {l}', 2)
        time.sleep(5)
        if self.processing: return
        self.lcd.lcd_clear()
        self.lcd.lcd_display_string('Now sleeping zZz')
        time.sleep(1)
        if self.processing: return
        self.lcd.backlight(0)

    def run(self):
        while True:
            self.display()
            time.sleep(2);

    def display(self):
        if (self.processing):
            return
        self.processing = True
        queueSize = len(self.queue)
        if (queueSize > -1):
            for idx, item in enumerate(self.queue):
                waitFactor = 60
                waitQuickFactor = 10
                scrollable = False
                lastItem = queueSize - 1 == idx
                self.queue.pop(0)
                self.lcd.lcd_clear()
                self.lcd.backlight(1)
                self.lcd.lcd_load_custom_chars(fontIcons)
                self.lcd.lcd_display_string(replaceIcon(item['l1']), 1)

                if "scrollable" in item and item['scrollable'] == True:
                    scrollable = True
                    string = replaceIcon(item['l2'])
                    stringLen = len(string)
                    start = time.perf_counter()
                    while True:
                        for i in range (0, stringLen - 16 + 1):
                            lcd_text = string[i:stringLen]
                            self.lcd.lcd_display_string(lcd_text, 2)
                            time.sleep(0.05)
                        time.sleep(1)
                        for i in range(stringLen, 14, -1):
                            lcd_text = string[i - 16 + 1: stringLen]
                            self.lcd.lcd_display_string(lcd_text, 2)
                            time.sleep(0.05)

                        clock = time.perf_counter() - start

                        if (lastItem and
                            queueSize - 1 != len(self.queue) and
                            clock > waitQuickFactor):
                            break
                        elif lastItem and clock > waitFactor:
                            break
                        time.sleep(1)                            

                else:
                    self.lcd.lcd_display_string(replaceIcon(item['l2']), 2)
               
                if (scrollable):
                    if lastItem and queueSize - 1 != len(self.queue):
                        continue
                else:
                    if (queueSize - 1 == idx):
                        x = 0
                        while x != waitFactor:
                            if (queueSize - 1 != len(self.queue) and x >= 5):
                                logger.info("new message incoming breaking long loop")
                                break
                            time.sleep(1)
                            x += 1
                    else:
                        x = 0
                        while x != waitQuickFactor:
                            time.sleep(1)
                            x += 1
                self.lcd.lcd_clear()
            self.lcd.backlight(0)
        self.processing = False

    def queueMessage(self, message):
        self.queue.append(message)

class HttpHandler(BaseHTTPRequestHandler):
    def _set_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        self._set_response()
        self.wfile.write("GET request for {}".format(self.path).encode('utf-8'))

    def do_POST(self):
        logger.info("Received payload")
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        logger.info("POST request : " + post_data.decode('utf-8'))
        
        try:
            body = json.loads(post_data)
        except ValueError as e:
            logger.error(e)
        logger.info(body)
        lcdPrint.queueMessage(body)

        self._set_response()
        self.wfile.write(b"OK\n")

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

class StoppableHTTPServer(HTTPServer):
    def run(self):
        try:
            self.serve_forever()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self.server_close()

def mqtt_on_connect(client, userdata, flags, rc):
    logger.info('Connected to the broker...')
    client.subscribe('display/i2c', 2)

def on_subscribe(client, obj, mid, granted_qos):
    logger.info("Subscribed: " + str(mid) + " " + str(granted_qos))

def mqtt_on_message(client, userdata, msg):
    logger.debug('received from queue:' + str(msg.payload))
    try:
        body = json.loads(msg.payload)
        lcdPrint.queueMessage(body)
    except TypeError:
        pass

def runHttp(server_class=StoppableHTTPServer, handler_class=HttpHandler, port=8080):
    server_address = ('', http_port)
    httpd = server_class(server_address, handler_class)
    logger.info('Started httpd...')
    httpd.run()

def runMqtt():
    client = mqtt.Client('I2C-daemon')
    client.enable_logger(logger)
    client.on_connect = mqtt_on_connect
    client.on_message = mqtt_on_message
    client.on_subscribe = on_subscribe
    client.connect(host=mqtt_host, port=mqtt_port, keepalive=60, bind_address="")
    client.loop_start()
    try:
        threading.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        client.loop_stop()
        client.disconnect()

def run():
    http = threading.Thread(name='http', target=runHttp)
    http.daemon = True

    mqtt = threading.Thread(name='mqtt', target=runMqtt)
    mqtt.daemon = True

    http.start()
    mqtt.start()

    try:
        threading.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping server..")

lcdPrint = LCDPrinter()

if __name__ == '__main__':
        run()
