#!/usr/bin/python3

from os.path import dirname
from pygame import mixer
from simplisafe import DeviceType
from simplisafe.devices import Keypad
from simplisafe.messages import Message
from simplisafe.pigpio import Transceiver

RX_315MHZ_GPIO = 27 # Connected to DATA pin of 315MHz receiver
TX_433MHZ_GPIO = 20 # Connected to DATA pin of 433MHz transmitter

class MyKeypad(Keypad):

    def _process_msg(self, msg: Message):
        print(msg.__class__.__name__ + " received from base station with serial number '" + msg.sn + "'")
        super()._process_msg(msg)

    def _send(self, msg: Message):
        super()._send(msg)
        print(msg.__class__.__name__ + " sent")

    def backlight(self, on: bool):
        if (on):
            print('Backlight on')
        else:
            print('Backlight off')

    def display(self):
        if self.page == self.Page.BOOT:
            print(self.Page.BOOT.value)
        elif self.page == self.Page.ALARM_STATUS:
            # Check modes
            print(str(Self.Page.ALARM_STATUS))
        elif self.page == self.Page.ENTER_DISARM_PIN or self.page == self.Page.ENTER_MENU_PIN:
            print(str(self.Page.ALARM_STATUS).format(":_<4".format(self._entry_buffer)))

with Transceiver(rx=RX_315MHZ_GPIO, tx=TX_433MHZ_GPIO) as txr:
    bs = MyKeypad(txr, "12345")
    while True:
        pass
