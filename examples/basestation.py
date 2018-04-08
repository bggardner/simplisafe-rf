#!/usr/bin/python3

from email.mime.text import MIMEText
from os.path import dirname
from pygame import mixer
from simplisafe import DeviceType
from simplisafe.devices import BaseStation
from simplisafe.messages import Message
from simplisafe.pigpio import Transceiver
from smtplib import SMTP

RX_433MHZ_GPIO = 27 # Connected to DATA pin of 433MHz receiver
TX_315MHZ_GPIO = 16 # Connected to DATA pin of 315MHz transmitter

components = [
    {"name": "Living Room", "type": DeviceType.MOTION_SENSOR, "sn": "1C3J9", "setting": BaseStation.MotionSensorSetting.ALARM_HOME_AND_AWAY},
    {"name": "Den", "type": DeviceType.MOTION_SENSOR, "sn": "1C3BL", "setting": BaseStation.MotionSensorSetting.ALARM_HOME_AND_AWAY},
    {"name": "Kitchen", "type": DeviceType.MOTION_SENSOR, "sn": "1C3BH", "setting": BaseStation.MotionSensorSetting.ALARM_HOME_AND_AWAY},
    {"name": "Master Bedroom", "type": DeviceType.KEYPAD, "sn": "167JC", "setting": BaseStation.KeypadSetting.PANIC_ENABLED},
    {"name": "Van Keychain", "type": DeviceType.KEYCHAIN_REMOTE, "sn": "1A174", "setting": BaseStation.KeychainRemoteSetting.ENABLED},
    {"name": "Lost Keychain", "type": DeviceType.KEYCHAIN_REMOTE, "sn": "18GUB", "setting": BaseStation.KeychainRemoteSetting.DISABLED},
#    {"name": "Garage Door", "type": DeviceType.ENTRY_SENSOR, "sn": "1R9CL", "setting": BaseStation.EntrySensorSetting.ALARM_HOME_AND_AWAY},
#    {"name": "Bathroom Window", "type": DeviceType.ENTRY_SENSOR, "sn": "1R414", "setting": BaseStation.EntrySensorSetting.ALARM_HOME_AND_AWAY},
#    {"name": "Porch Door", "type": DeviceType.ENTRY_SENSOR, "sn": "1QKGG", "setting": BaseStation.EntrySensorSetting.ALARM_HOME_AND_AWAY},
#    {"name": "Shed", "type": DeviceType.ENTRY_SENSOR, "sn": "1RBR1", "setting": BaseStation.EntrySensorSetting.ALARM_HOME_AND_AWAY},
    ]

class MyBaseStation(BaseStation):

    def _process_msg(self, msg: Message):
        print(msg.__class__.__name__ + " received from '" + self._components.get(msg.sn).get('name') + "' with serial number '" + msg.sn + "' and sequence '" + str(msg.sequence) + "'")
        super()._process_msg(msg)

    def _send(self, msg: Message):
        print(msg.__class__.__name__ + " sent")

    def alarm(self):
        msg = MIMEText('') # TODO
        msg['Subject'] = 'SimpliSafe Alarm!'
        self.send_email(msg)

    def alert(self):
        msg = MIMEText('') # TODO
        msg['Subject'] = 'SimpliSafe Alert!'
        self.send_email(msg)

    def armed_away(self):
        msg = MIMEText('') # TODO
        msg['Subject'] = 'SimpliSafe Armed - Away'
        self.send_email(msg)

    def armed_home(self):
        msg = MIMEText('') # TODO
        msg['Subject'] = 'SimpliSafe Armed - Home'
        self.send_email(msg)

    def disarm(self):
        msg = MIMEText('') # TODO
        msg['Subject'] = 'SimpliSafe Disarmed'
        self.send_email(msg)

    def door_chime(self):
        mixer.init()
        mixer.music.load(dirname(__file__) + '/sounds/door_chime.mp3')
        mixer.music.set_volume(self._settings.get('voice_volume', 100) / 100)
        mixer.music.play()

    def send_email(self, msg: MIMEText):
        msg['From'] = 'pi@localhost'
        msg['To'] = 'remote@host.com'
        try:
            s = SMTP('localhost')
            s.send_message(msg)
            s.quit()
        except:
            print('E-mail send failed.')

    def start_siren(self):
        mixer.init()
        mixer.music.load(dirname(__file__) + '/sounds/siren.mp3')
        mixer.music.set_volume(self._settings.get('siren_volume', 100) / 100)
        mixer.music.play(-1)

    def stop_siren(self):
        if mixer and mixer.get_init():
            mixer.music.stop()
            mixer.quit()

with Transceiver(rx=RX_433MHZ_GPIO, tx=TX_315MHZ_GPIO) as txr:
    bs = MyBaseStation(txr, "123456", 8331, components=components)
    while True:
        pass
