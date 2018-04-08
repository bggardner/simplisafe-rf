#!/usr/bin/python3
from simplisafe import *
from simplisafe.messages import *
from threading import Thread, Timer
from time import time

# Level 1
class AbstractTransceiver:

    def fileno(self):
        raise NotImplementedError

    def recv(self):
        raise NotImplementedError

    def send(self, msg: Message):
        raise NotImplementedError


class AbstractDevice:

    sequence = 0

    def __init__(self, txr: AbstractTransceiver, sn: str):
        self.txr = txr
        self.sn = sn
        Thread(target=self._recv, daemon=True).start()

    def _inc(self):
        self.sequence += 1
        self.sequence %= 0xF

    def _recv(self):
        while True:
            self._process_msg(self.txr.recv())

    def _process_msg(self, msg: Message):
        raise NotImplementedError

    def _send(self, msg: Message):
        self.txr.send(msg)
        self._inc()

# Level 2

class BaseStation(AbstractDevice):

    class AlarmType:
        pass

    class AlertType:
        ALARM_OFF = "Alarm off"
        SENSOR_NOT_RESPONDING = "Sensor not responding"
        NO_LINK_TO_DISPATCHER = "No link to dispatcher"
        SETTINGS_SYNCHRONIZED = "Your settings have been synchronized"

    class Settings:
        class Light(UniqueIntEnum):
            NO = 0
            YES = 1
        class VoicePrompts(UniqueIntEnum):
            NO = 0
            YES = 1
            ERROR_ONLY = 2
        class DoorChime(UniqueIntEnum):
            NO = 0
            YES = 1

    class KeypadSetting(UniqueIntEnum):
        PANIC_ENABLED = 1
        PANIC_DISABLED = 2

    class KeychainRemoteSetting(UniqueIntEnum):
        DISABLED = 0
        ENABLED = 1
        PANIC_DISABLED = 2

    class PanicButtonSetting(UniqueIntEnum):
        AUDIBLE_ALARM = 1
        SILENT_ALARM = 2

    class MotionSensorSetting(UniqueIntEnum):
        DISABLED = 0
        ALARM_HOME_AND_AWAY = 1
        ALARM_AWAY_ONLY = 2
        NO_ALARM_ALERT_ONLY = 64

    class EntrySensorSetting(UniqueIntEnum):
        DISABLED = 0
        ALARM_HOME_AND_AWAY = 1
        ALARM_AWAY_ONLY = 2
        NO_ALARM_ALERT_ONLY = 64

    class GlassbreakSensorSetting(UniqueIntEnum):
        DISABLED = 0
        ALARM_HOME_AND_AWAY = 1
        ALARM_AWAY_ONLY = 2

    class CODetectorSetting(UniqueIntEnum):
        ALWAYS_ON = 255

    class SmokeDetectorSetting(UniqueIntEnum):
        ALWAYS_ON = 255

    class WaterSensorSetting(UniqueIntEnum):
        ALWAYS_ON = 255

    class FreezeSensorSetting(UniqueIntEnum):
        DISABLED = 0

    def __init__(self, txr: AbstractTransceiver, sn: str, master_pin, **kwargs):
        self.sn = sn
        self.master_pin = master_pin
        if "duress_pin" in kwargs and not kwargs["duress_pin"] is None:
            self.duress_pin = kwargs["duress_pin"]
        else:
            self.duress_pin = None
        self._pins = []
        if "additional_pins" in kwargs and isinstance(kwargs["additional_pins"], list):
            for i in kwargs["additional_pins"]:
                d = kwargs["additional_pins"][i]
                if "pin" in d:
                    if "name" in d:
                        self.add_pin(d.pin, d.name)
                    else:
                        self.add_pin(d.pin)
                else:
                    raise ValueError
        self._settings = {"light": BaseStation.Settings.Light.YES, "voice_prompts": BaseStation.Settings.VoicePrompts.YES, "door_chime": BaseStation.Settings.DoorChime.YES, "voice_volume": 35, "siren_volume": 100, "siren_duration": 5, "entry_delay_away": 30, "entry_delay_home": 1, "exit_delay": 45, "dialing_prefix": None}
        if "settings" in kwargs:
            self.settings = kwargs["settings"]
        self._components = {}
        if "components" in kwargs and isinstance(kwargs["components"], list):
            for c in kwargs["components"]:
                self.add_component(c.get("name", ""), c.get("type"), c.get("sn"), c.get("setting", None), c.get("instant_trip", None))
        self._error_flags = 0
        self._armed = ArmedState.OFF
        self._ess = 0
        self._time_left = 0
        self._siren_timer = None
        self._heartbeat_timer()
        self._test_mode_timer()
        super().__init__(txr, sn)
        for kp in self.keypads:
            self._send(BaseStationKeypadPowerOnUpdate(kp.get("sn"), self.sequence, self.sn, self._error_flags, self._armed, self._ess, self._time_left, 0xC)) # TODO: Why 0xC?
            self._send(BaseStationKeypadTestModeOnUpdate(kp.get("sn"), self.sequence, self.sn))
            self._send(BaseStationKeypadClearSensorError1Update(kp.get("sn"), self.sequence, self.sn))
            self._send(BaseStationKeypadClearSensorError2Update(kp.get("sn"), self.sequence, self.sn))
            self._send(BaseStationKeypadClearSensorError3Update(kp.get("sn"), self.sequence, self.sn))
            self._send(BaseStationKeypadClearSensorError4Update(kp.get("sn"), self.sequence, self.sn))

    def _alarm(self, silent=False):
        self._cancel_countdown()
        if not silent:
            if self._siren_timer and self._sirent_timer.is_alive():
                pass # Don't restart siren timer
            else:
                self.start_siren()
                self._siren_timer = Timer(60 * self._settings["siren_duration"], self.stop_siren)
                self._sirent_timer.start()
        self.alarm()

    def _arm_away(self):
        self._armed = ArmedStatus.ARMING_AWAY
        self._time_left = self._settings['exit_delay']
        self._countdown()

    def _arm_home(self):
        self._armed = ArmedStatus.ARMED_HOME
        self.arm_home()

    def _cancel_countdown(self):
        if self._time_left_timer is not None and self._time_left_timer.is_alive():
            self._time_left_timer.cancel()
        self._time_left = 0

    def _countdown(self):
        if not self.is_armed() and not self.is_arming():
            self._cancel_countdown()
        elif self.is_armed():
            if self._time_left == 0:
                self._alarm()
            else:
                self._time_left -= 1
                print("{:d} seconds left before alarm".format(self._time_left))
                self._time_left_timer = Timer(1, self._countdown)
                self._time_left_timer.start()
        elif self.is_arming():
            if self._time_left == 0:
                self._armed = ArmedState.ARMED_AWAY
                self.arm_away()
            else:
                self._time_left -= 1
                print("{:d} seconds left before armed".format(self._time_left))
                self._time_left_timer = Timer(1, self._countdown)
                self._time_left_timer.start()

    def _disarm(self):
        self._armed = ArmedState.OFF
        if self._siren_timer and self._siren_timer.is_alive():
            self._siren_timer.cancel()
        self.stop_siren()
        self.disarm()

    def _heartbeat_timer(self):
        for sn in self._components:
            c = self._components[sn]
            if 'last_heartbeat' in c:
                dt = time() - c['last_heartbeat']
                if dt > self.HEARTBEAT_TIMEOUT:
                    self.alert(self.AlertType.SENSOR_NOT_RESPONDING, sn)
            else:
                c['last_heartbeat'] = time()
                self._components.update({sn: c})
            Timer(24 * 3600, self._heartbeat_timer).start()

    def _process_msg(self, msg: Message):
        if isinstance(msg, BaseStationKeypadMessage):
            return # BaseStations do not accept BaseStationKeypad Messages
        if not msg.sn in self._components:
            return # Component not enrolled
        c = self._components.get(msg.sn)
        setting = c.get('setting')
        if isinstance(msg, KeypadMessage):
            if isinstance(msg, KeypadRemoveComponentScrollMenuRequest) or isinstance(msg, KeypadRemoveComponentMenuRequest):
                if isinstance(msg, KeypadRemoveComponentScrollMenuRequest):
                    n = msg.n
                else:
                    n = 0
                c_sn = list(self._components)[n]
                c_type = self._components.get(c_sn).get('type')
                left_arrow = n != 0
                right_arrow = (len(self._components) - 1) != n
                if c_type == DeviceType.KEYPAD:
                    self._send(BaseStationKeypadRemoveKeypadScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.KEYCHAIN_REMOTE:
                    self._send(BaseStationKeypadRemoveKeychainRemoteScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.PANIC_BUTTON:
                    self._send(BaseStationKeypadRemovePanicButtonScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.MOTION_SENSOR:
                    self._send(BaseStationKeypadRemoveMotionSensorScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.ENTRY_SENSOR:
                    self._send(BaseStationKeypadRemoveEntrySensorScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.GLASSBREAK_SENSOR:
                    self._send(BaseStationKeypadRemoveGlassbreakSensorScrolMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.CO_DETECTOR:
                    self._send(BaseStationKeypadRemoveCoDetectorScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.SMOKE_DETECTOR:
                    self._send(BaseStationKeypadRemoveSmokeDetectorScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.WATER_SENSOR:
                    self._send(BaseStationKeypadRemoveWaterSensorScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                elif c_type == DeviceType.FREEZE_SENSOR:
                    self._send(BaseStationKeypadRemoveFreezeSensorScrollMenuResponse(msg.sn, self.sequence, c_sn, left_arrow, right_arrow))
                else:
                    raise NotImplementedError(str(c_type))
            elif isinstance(msg, KeypadAlarmPinRequest):
                if msg.pin == self.duress_pin or  msg.pin == self.master_pin or any(d['pin'] == msg.pin for d in self.pins):
                    self._send(BaseStationKeypadAlarmPinResponse(msg.sn, self.sequence, self.sn, BaseStationKeypadAlarmPinResponse.ResponseType.DISARM)) # TODO: Respond with alarm source, if any
                    self._disarm()
                    if msg.pin == self.duress_pin:
                        self._alarm(True)
                else:
                    self._send(BaseStationKeypadAlarmPinResponse(msg.sn, self.sequence, self.sn, BaseStationKeypadAlarmPinResponse.ResponseType.INVALID))
            elif isinstance(msg, KeypadMenuPinRequest):
                if msg.pin == self.master_pin:
                    self._send(BaseStationKeypadValidMenuPinResponse(msg.sn, self.sequence))
                else:
                    self._send(BaseStationKeypadInvalidMenuPinResponse(msg.sn, self.sequence))
            elif isinstance(msg, KeypadNewPinRequest):
                self._master_pin = msg.pin
            elif isinstance(msg, KeypadExtendedStatusRequest):
                self._send(BaseStationKeypadExtendedStatusResponse(msg.sn, self.sequence, self.sn, self._error_flags, self._armed, self._ess, self._time_left))
            elif isinstance(msg, KeypadTestModeOnRequest):
                self._test_mode = True # TODO: Test Mode
                self._send(BaseStationKeypadTestModeOnResponse(msg.sn, self.sequence, self.sn))
            elif isinstance(msg, KeypadTestModeOffRequest):
                self._test_mode = False
                self._send(BaseStationKeypadTestModeOffResponse(msg.sn, self.sequence, self.sn))
            elif isinstance(msg, KeypadHomeRequest):
                self._arm_home()
                self._send(BaseStationKeypadHomeResponse(msg.sn, self.sequence, self.sn))
            elif isinstance(msg, KeypadPanicRequest):
                if setting == self.KeypadSetting.PANIC_ENABLED:
                    self._alarm()
            elif isinstance(msg, KeypadAwayRequest):
                self._arm_away()
                self._send(BaseStationKeypadAwayResponse(msg.sn, self.sequence, self.sn))
            elif isinstance(msg, KeypadOffRequest):
                self._send(BaseStationKeypadOffRequest(msg.sn, self.sequence, self.sn))
            elif isinstance(msg, KeypadEnterMenuRequest):
                self._send(BaseStationKeypadEnterMenuResponse(msg.sn, self.sequence))
            elif isinstance(msg, KeypadExitMenuRequest):
                self._send(BaseStationKeypadExitMenuResponse(msg.sn, self.sequence))
            elif isinstance(msg, KeypadChangePinMenuRequest):
                self._send(BaseStationKeypadChangePinMenuResponse(msg.sn, self.sequence))
            elif isinstance(msg, KeypadChangePinConfirmMenuRequest):
                self._send(BaseStationKeypadChangePinConfirmMenuResponse(msg.sn, self.sequence))
            elif isinstance(msg, KeypadAddComponentMenuRequest):
                self._send(BaseStationKeypadAddComponentMenuResponse(msg.sn, self.sequence))
            elif isinstance(msg, KeypadRemoveComponentSelectMenuRequest):
                self._send(BaseStationKeypadRemoveComponentSelectMenuResponse(msg.sn, self.sequence))
            elif isinstance(msg, KeypadAddComponentLastTypeMenuRequest):
                 pass # TODO
            elif isinstance(msg, KeypadPrefixRequest):
                self._settings.update({'dialing_prefix': msg.prefix})
                self._send(BaseStationKeypadNewPrefixResponse(msg.sn, self.sequence))
            elif isinstance(msg, AbstractKeypadModifyComponentMenuRequest):
                if isinstance(msg, KeypadRemoveComponentConfirmMenuRequest):
                    self.remove_component(msg.c_sn)
                    self._send(BaseStationKeypadRemoveComponentConfirmMenuResponse(msg.sn, self.sequence))
                else:
                    if msg.c_sn in self._components: # Check DeviceType?
                       response_type = AbstractBaseStationKeypadAddComponentSerialMenuResponse.ResponseType.COMPONENT_ALREADY_ADDED
                    else:
                        if isinstance(msg, KeypadAddKeypadMenuRequest):
                            c_type = DeviceType.KEYPAD
                            msg_class = BaseStationKeypadAddKeypadMenuResponse
                        elif isinstance(msg, KeypaddAddKeychainRemoteMenuRequest):
                            c_type = DeviceType.KEYCHAIN_REMOTE
                            msg_class = BaseStationKeypadAddKeychainRemoteMenuResponse
                        elif isinstance(msg, KeypadAddPanicButtonMenuRequest):
                            c_type = DeviceType.PANIC_BUTTON
                            msg_class = BaseStationkeypadAddPanicButtonMenuResponse
                        elif isinstance(msg, KeypadAddMotionSensorMenuRequest):
                            c_type = DeviceType.MOTION_SENSOR
                            msg_class = BaseStationKeypadAddMotionSensorMenuResponse
                        elif isinstance(msg, KeypadAddEntrySensorMenuRequest):
                            c_type = DeviceType.ENTRY_SENSOR
                            msg_class = BaseStationKeypadAddEntrySensorMenuResponse
                        elif isinstance(msg, KeypadAddGlassbreakSensorMenuRequest):
                            c_type = DeviceType.GLASSBREAK_SENSOR
                            msg_class = BaseStationKeypadAddGlassbreakSensorMenuResponse
                        elif isisntance(msg, KeypadAddCoDetectorMenuRequest):
                            c_type = DeviceType.CO_DETECTOR
                            msg_class = BaseStationKeypadAddCoDetectorMenuResponse
                        elif isinstance(msg, KeypadAddSmokeDetectorMenuRequest):
                            c_type = DeviceType.SMOKE_DETECTOR
                            msg_class = BaseStationKeypadAddSmokeDetectorMenuResponse
                        elif isinstance(msg, KeypadAddWaterSensorMenuRequest):
                            c_type = DeviceType.WATER_SENSOR
                            msg_class = BaseStationKeypadAddWaterSensorMenuResponse
                        elif isinstance(msg, KeypadAddFreezeSensorMenuRequest):
                            c_type = DeviceType.FREEZE_SENSOR
                            msg_class = BaseStationKeypadAddFreezeSensorMenuResponse
                        else:
                            raise NotImplementedError
                        self.add_component("", c_type, msg.c_sn)
                        response_type = AbstractBaseStationKeypadAddComponentSerialMenuResponse.ResponseType.COMPONENT_ADDED
                    self._send(msg_class(msg.sn, self.sequence, response_type))
            elif isinstance(msg, KeypadAddComponentTypeMenuRequest):
                self._send(BaseStationKeypadAddComponentTypeMenuResponse(msg.sn, self.sequence))
        elif isinstance(msg, KeychainRemoteMessage):
            if not (setting == self.KeychainRemoteSetting.DISABLED):
                if msg.event_type == KeychainRemoteMessage.EventType.PANIC:
                    if not (setting == self.KeychainRemoteSetting.PANIC_DISABLED):
                        self._alarm()
                elif msg.event_type == KeychainRemoteMessage.EventType.AWAY:
                    self._arm_away()
                elif msg.event_type == KeychainRemoteMessage.EventType.OFF:
                    self._disarm()
        elif isinstance(msg, PanicButtonMessage):
            if msg.event_type == PanicButtonMessage.EventType.PANIC:
                if setting == self.PanicButtonSetting.AUDIBLE_ALARM:
                    self._alarm()
                elif setting == self.PaicButtonSetting.SILENT_ALARM:
                    self._alarm(True)
        elif isinstance(msg, MotionSensorMessage):
            if msg.event_type == MotionSensorMessage.EventType.MOTION:
                if ((setting == self.MotionSensorSetting.ALARM_HOME_AND_AWAY and self.is_armed())
                    or (setting == self.MotionSensorSetting.ALARM_AWAY_ONLY and self.is_armed_away())):
                    self._trip(self._alarm, c.get('instant_trip'))
                elif setting == self.MotionSensorSetting.NO_ALARM_ALERT_ONLY and self.is_armed():
                    self._trip(self._alert, c.get('instant_trip'))
        elif isinstance(msg, EntrySensorMessage):
            if msg.event_type == EntrySensorMessage.EventType.OPEN:
                if ((setting == self.EntrySensorSetting.ALARM_HOME_AND_AWAY and self.is_armed())
                    or (setting == self.EntrySensorSetting.ALARM_AWAY_ONLY and self.is_armed_away())):
                    self._trip(self._alarm, c.get('instant_trip'))
                elif setting == self.EntrySensorSetting.NO_ALARM_ALERT_ONLY and self.is_armed():
                    self._trip(self._alert, c.get('instant_trip'))
        elif isinstance(msg, GlassbreakSensorMessage):
            if msg.event_type == GlassbreakSensorMessage.EventType.GLASSBREAK:
                if ((setting == self.GlassbreakSensorSetting.ALARM_HOME_AND_AWAY and self.is_armed())
                    or (setting == self.GlassbreakSensorSetting.ALARM_AWAY_ONLY and self.is_armed_away())):
                    self._trip(self._alarm, c.get('instant_trip'))
        else:
            raise NotImplementedError
    
    def _trip(self, trip_function, instant_trip=False):
        if instant_trip:
            trip_function()
        elif self._time_left == 0: # Don't re-trip
            if self.is_armed_away():
                self._time_left = self._settings["entry_delay_away"]
            elif self.is_armed_away():
                self._time_left = self._settings["entry_delay_home"]
            self._countdown()

    def add_component(self, name: str, cls: DeviceType, sn: str, setting=None, instant_trigger=None):
        name = name[:22] # Maxlength of 22
        if cls == DeviceType.BASE_STATION:
            raise RuntimeException("Must be a Component")
        if cls == DeviceType.KEYPAD:
            setting = self.KeypadSetting(setting)
        elif cls == DeviceType.KEYCHAIN_REMOTE:
            setting = self.KeychainRemoteSetting(setting)
        elif cls == DeviceType.MOTION_SENSOR:
            setting = self.MotionSensorSetting(setting)
        elif cls == DeviceType.ENTRY_SENSOR:
            setting = self.EntrySensorSetting(setting)
        elif cls == DeviceType.GLASSBREAK_SENSOR:
            setting = self.GlassbreakSensorSetting(setting)
        elif cls == DeviceType.CO_DETECTOR:
            setting = self.CoDetectorSetting(setting)
        elif cls == DeviceType.SMOKE_DETECTOR:
            setting = self.SmokeDetectorSetting(setting)
        elif cls == DeviceType.WATER_SENSOR:
            setting = self.WaterSensorSetting(setting)
        elif cls == DeviceType.FREEZE_SENSOR:
            setting = self.FreezeSensorSetting(setting)
        if cls in [DeviceType.ENTRY_SENSOR, DeviceType.MOTION_SENSOR, DeviceType.GLASSBREAK_SENSOR]:
            instant_trigger = bool(instant_trigger)
        else:
            instant_trigger = None
        self._components.update({sn: {"name": name, "type": cls, "setting": setting, "instat_trigger": instant_trigger}})

    def add_pin(self, pin, name: str=''):
        self._pins.update({"name": name, "pin": Validator.pin(pin)})

    @property
    def components(self):
        components = []
        for i in self._components:
            c = self._components[i]
            c["sn"] = i
            components.append(c)
        return components

    @property
    def duress_pin(self):
        return self._duress_pin

    @duress_pin.setter
    def duress_pin(self, pin):
        if pin is None:
            self._duress_pin = None
        else:
            self._duress_pin = Validator.pin(pin)

    def is_armed(self):
        return self.is_armed_away() or self.is_armed_home()

    def is_armed_away(self):
        return self._armed == ArmedState.ARMED_AWAY

    def is_armed_home(self):
        return self._armed == ArmedState.ARMED_HOME

    def is_arming(self):
        return self._armed == ArmedState.ARMING_AWAY

    @property
    def keypads(self):
        return {k: v for k, v in self.components.items() if v["type"] == DeviceType.KEYPAD}

    @property
    def master_pin(self):
        return self._master_pin

    @master_pin.setter
    def master_pin(self, pin):
        self._master_pin = Validator.pin(pin)

    @property
    def pins(self):
        return self._pins

    def remove_component(self, sn):
        if sn in self._components:
            self._components.pop(sn)

    def remove_pin(self, d):
        del self._pins[d["name"]]

    @property
    def settings(self):
        return self._settings

    @settings.setter
    def settings(self, settings):
        if not isinstance(settings, dict):
            raise ValueError("Settings must be a dict")
        if "light" in settings:
            self._settings.update({"light": BaseStation.Settings.Light(settings["light"])})
        if "voice_prompt" in settings:
            self._settings.update({"voice_prompt": BaseStation.Settings.VoicePrompt(settings["voice_prompt"])})
        if "door_chime" in settings:
            self._settings.update({"door_chime": BaseStation.Settings.DoorChime(settings["door_chime"])})
        if "voice_volume" in settings:
            vv = int(settings["voice_volume"], 0)
            if not 0 <= vv <= 100:
                raise ValueError("Voice/Door Chime Volume must be in range 0-100")
            self._settings.update({"voice_volume": vv})
        if "siren_volume" in settings:
            sv = int(settings["siren_volume"], 0)
            if not 0 <= sv <= 100:
                raise ValueError("Alarm Siren Volume must be in range 0-100")
            self._settings.update({"siren_volume": sv})
        if "siren_duration" in settings:
            sd = int(settings["siren_duration"], 0)
            if sd < 0:
                raise ValueError("Alarm Siren Duration must be positive")
            self._settings.update({"siren_duration": sd})
        if "entry_delay_away" in settings:
            ed = int(settings["entry_delay_away"], 0)
            if not 30 <= ed <= 250:
                raise ValueError("Entry Delay (away mode) must be in range 30-250")
            self._settings.update({"entry_delay_away": ed})
        if "entry_delay_home" in settings:
            ed = int(settings["entry_delay_home"], 0)
            if not 1 <= ed <= 250:
                raise ValueError("Entry Delay (home mode) must be in range 1-250")
            self._settings.update({"entry_delay_home": ed})
        if "exit_delay" in settings:
            ed = int(settings["exit_delay"], 0)
            if not 45 <= ed <= 120:
                raise ValueError("Exit Delay must be in range 45-120")
            self._settings.update({"exit_delay": ed})
        if "dialing_prefix" in settings:
            dp = Validator.prefix(settings["dialing_prefix"])
            self._settings.update({"dialing_prefix": dp})

    # Methods to be (optionally) overridden by child class(es)
    def alarm(self):
        pass # Called when alarm is triggered

    def alert(self):
        pass # Called when voice alert is triggered

    def arm_away(self):
        pass # Called when system is armed (away, after delay)

    def arm_home(self):
        pass # Called when system is armed (home)

    def disarm(self):
        pass # Called when system is disarmed

    def door_chime(self):
        pass # Called when door chime is triggered

    def start_siren(self):
        pass # Called when siren should start

    def stop_siren(self):
        pass # Called when siren should stop

class Component(AbstractDevice):
    pass

# Level 3

class Keypad(Component):

    class Mode(UniqueEnum):
        OFF = 'Off'
        AWAY = 'Away'
        HOME = 'Home'

    class Page(UniqueEnum):
        BOOT = 'Welcome to SimpliSafe'
        ALARM_STATE = 'Alarm {:s}'
        SENSOR_ERROR = 'Error:Sensor # {:s}'
        ENTER_DISARM_PIN = 'Enter Pin:{:s}'
        ENTER_MENU_PIN = 'Enter Pin:{:s}'

    class Menu(UniqueEnum):
        CHANGE_PIN = '1) Change PIN'
        DIALING_PREFIX = '2) Dialing prefix'
        ADD_COMPONENT = '3) Add component'
        REMOVE_COMPONENT = '4) Remove component'
        TEST = '5) Test'
        EXIT_MENU = '6) Exit Menu'

    class AddComponentMenu(UniqueEnum):
        ENTRY_SENSOR = 'Entry Sensor'
        MOTION_SENSOR = 'Motion Sensor'
        PANIC_BUTTON = 'Panic Button'
        KEYPAD = 'Keypad'
        KEYCHAIN_REMOTE = 'Keychain Remote'
        GLASSBREAK_SENSOR = 'Glassbreak Sensor'
        CO_DETECTOR = 'CO Detector'
        SMOKE_DETECTOR = 'Smoke Detector'
        WATER_SENSOR = 'Water Sensor'
        FREEZE_SENSOR = 'Freeze Sensor'

    def __init__(self, txr: AbstractTransceiver, sn: str):
        self._page = self.Page.BOOT
        self._menu_page = None
        self._add_component_menu_page = None
        self._remove_component_menu_page = None
        self._backlight_timer = None
        self._time_left_timer = None
        self.error_flags = None
        self.armed = None
        self.ess = None
        self.time_left = None
        super().__init__(txr, sn)
        self._display(False)
        self._send(KeypadExtendedStatusRequest(self.sn, self.sequence))

    def _cancel_countdown(self):
        if self._time_left_timer is not None and self._time_left_timer.is_alive():
            self._time_left_timer.cancel()
        self._time_left = 0

    def _countdown(self):
        if not self.is_armed() and not self.is_arming():
            self._cancel_countdown()
        elif self._time_left != 0:
            self._time_left -= 1
            self._time_left_timer = Timer(1, self._countdown)
            self._time_left_timer.start()
            self.warning_beep()

    def _display(self, backlight: bool=True):
        if self._backlight_timer and self._backlight_timer.is_alive():
            self._backlight_timer.cancel()
        self.backlight(backlight)
        if backlight:
            self._backlight_timer = Timer(20, self.backlight, [False])
            self._backlight_timer.start()
        self.display()

    def _inc(self):
        self.sequence += 4
        self.sequence %= 0xF

    def _menu_enter(self):
        pass # TODO

    def _menu_next(self):
        if self._menu_page == Keypad.Menu.CHANGE_PIN:
            self._menu_page == Keypad.Menu.DIALING_PREFIX
        elif self._menu_page == Keypad.Menu.DIALING_PREFIX:
            self._menu_page == Keypad.Menu.ADD_COMPONENT
        elif self._menu_page == Keypad.Menu.ADD_COMPONENT:
            if self._add_component_menu_page is None:
                self._menu_page = Keypad.Menu.REMOVE_COMPONENT
            elif self._add_component_menu_page == Keypad.AddComponentMenu.ENTRY_SENSOR:
                self._add_component_menu_page = Keypad.AddComponentMenu.MOTION_SENSOR
            elif self._add_component_menu_page == Keypad.AddComponentMenu.MOTION_SENSOR:
                self._add_component_menu_page = Keypad.AddComponentMenu.PANIC_BUTTON
            elif self._add_component_menu_page == Keypad.AddComponentMenu.PANIC_BUTTON:
                self._add_component_menu_page = Keypad.AddComponentMenu.KEYPAD
            elif self._add_component_menu_page == Keypad.AddComponentMenu.KEYPAD:
                self._add_component_menu_page = Keypad.AddComponentMenu.KEYCHAIN_REMOTE
            elif self._add_component_menu_page == Keypad.AddComponentMenu.KEYCHAIN_REMOTE:
                self._add_component_menu_page = Keypad.AddComponentMenu.GLASSBREAK_SENSOR
            elif self._add_component_menu_page == Keypad.AddComponentMenu.GLASSBREAK_SENSOR:
                self._add_component_menu_page = Keypad.AddComponentMenu.CO_DETECTOR
            elif self._add_component_menu_page == Keypad.AddComponentMenu.CO_DETECTOR:
                self._add_component_menu_page = Keypad.AddComponentMenu.SMOKE_DETECTOR
            elif self._add_component_menu_page == Keypad.AddComponentMenu.SMOKE_DETECTOR:
                self._add_component_menu_page = Keypad.AddComponentMenu.WATER_SENSOR
            elif self._add_component_menu_page == Keypad.AddComponentMenu.WATER_SENSOR:
                self._add_component_menu_page = Keypad.AddComponentMenu.FREEZE_SENSOR
                msg = KeypadAddComponentLastTypeMenuRequest(self.sn, self.sequence)
                self._send(msg)
                Timer(1, self._send, [msg])
                Timer(2, self._send, [msg])
            elif self._add_component_menu_page == Keypad.AddComponentMenu.FREEZE_SENSOR:
                pass
            else:
                raise RuntimeError("Unknown Add Component Menu Page")
        elif self._menu_page == Keypad.Menu.REMOVE_COMPONENT:
            if self._remove_component_menu_page is None:
                self._menu_page = Keypad.Menu.TEST
            else:
                self._remove_component_menu_page += 1
                self._send(KeypadRemoveComponentScrollMenuRequest(self.sn, self.sequence, self._remove_component_menu_n))
        elif self._menu_page == Keypad.Menu.TEST:
            self._menu_page = Keypad.Menu.EXIT_MENU
        else:
            pass
        self._display()

    def _menu_prev(self):
        pass # TODO

    def _process_msg(self, msg: Message):
        if not isinstance(msg, BaseStationKeypadMessage):
            return
        if msg.sn != self.sn:
            return
        if isinstance(msg, (BaseStationKeypadExtendedStatusResponse, BaseStationKeypadExtendedStatusUpdate, BaseStationKeypadExtendedStatusRemoteUpdate)):
            self.error_flags = msg.flags
            self.armed = msg.armed
            self.ess = msg.ess
            self.time_left = msg.tl
            self._countdown()
        elif isinstance(msg, BaseStationKeypadStatusUpdate):
            self.error_flags = msg.flags
        elif isinstance(msg, BaseStationKeypadDisarmPinResponse):
            pass
        elif isinstance(msg, BaseStationKeypadInvalidMenuPinResponse):
            self._enter_menu_timer.cancel()
            self._entry_buffer = ''
            self._page = Keypad.Page.ENTER_MENU_PIN
            self._enter_menu_timer = Time(5, self._menu_cancel)
        elif isinstance(msg, BaseStationKeypadValidMenuPinResponse):
            self._enter_menu_timer.cancel()
            self._menu_page = Keypad.Menu.CHANGE_PIN
        elif isinstance(msg, BaseStationKeypadHomeResponse):
            pass
        elif isinstance(msg, BaseStationKeypadAwayResponse):
            pass
        elif isinstance(msg, BaseStationKeypadOffRemoteUpdate):
            pass
        elif isinstance(msg, BaseStationKeypadEnterMenuResponse):
            self._page = Keypad.Page.ENTER_MENU_PIN
            self._enter_menu_timer = Timer(5, self._menu_cancel)
        elif isinstance(msg, BaseStationKeypadNewPrefixResponse):
            pass
        # To be continued
        else:
            return
        self._display()

    # Utility functions
    def in_menu(self):
        return self._menu_page is not None

    def is_armed(self):
        return self.is_armed_away() or self.is_armed_home()

    def is_armed_away(self):
        return self._armed == ArmedState.ARMED_AWAY

    def is_armed_home(self):
        return self._armed == ArmedState.ARMED_HOME

    def is_arming(self):
        return self._armed == ArmedState.ARMING_AWAY

    def is_editing(self):
        is_editing = False
        is_editing |= self.page == Keypad.Page.ENTER_DISARM_PIN
        is_editing |= self.page == Keypad.Page.ENTER_MENU_PIN
        return is_editing

    @property
    def mode(self):
        if self._armed == ArmedState.OFF:
            mode = Keypad.Mode.OFF
        elif self._armed == ArmedState.ARMING_AWAY or self._armed == ArmedState.ARMED_AWAY:
            mode = Keypad.Mode.AWAY
        elif self._armed == ArmedState.ARMING_HOME or self._armed == ArmedState.ARMED_HOME:
            mode = Keypad.Mode.HOME
        else:
            raise RuntimeError
        return mode

    @property
    def page(self):
        return self._page

    # Buttons
    def away(self):
        if self.in_menu():
            self._menu_enter()
        else:
            self._send(KeypadAwayRequest(self.sn, self.sequence))
        self.button_beep()

    def off(self):
        if self.in_menu():
            self._menu_prev()
        else:
            self._send(KeypadOffRequest(self.sn, self.sequence))
        self.button_beep()

    def home(self):
        if self.in_menu():
            self._menu_next()
        else:
            self._send(KeypadHomeRequest(self.sn, self.sequence))
        self.button_beep()

    def numpad(self, n):
        n = int(n)
        if not 0 <= n <= 9:
            raise ValueError
        if self.page == Keypad.Page.ALARM_STATUS or self.page == Keypad.Page.SENSOR_ERROR:
            self._entry_buffer = str(n)
            self._page = Keypad.Page.ENTER_DISARM_PIN
        elif self.page == Keypad.Page.ENTER_DISARM_PIN:
            self._entry_buffer += str(n)
        #TODO: Serial number input
        self._display()
        self.button_beep()

    def menu(self):
        if self.in_menu():
            self._menu_cancel()
        else:
            self._send(KeypadEnterMenuRequest(self.sn, self.sequence))
        self.button_beep()

    def panic(self):
        self._send(KeypadPanicRequest(self.sn, self.sequence))
        self.button_beep()

    def delete(self):
        if self.is_editing():
            self._entry_buffer = self._entry_buffer[:-1]
            self._display()
        elif self.in_menu():
            self._prev()
        self.button_beep()

    # Implementation-specific functions to be overridden by subclasses
    def button_beep(self):
        pass

    def display(self):
        pass

    def backlight(self, on: bool):
        pass

    def warning_beep(self):
        pass


class Sensor(Component):

    def __init__(self, txr: AbstractTransceiver, sn: str):
        self._current_msg = None # Repeated message
        self._t = None # Timer object for repeated message
        self._tx_count = 0 # Number of repeated transmissions
        super().__init__(txr, sn)

    def _recv(self):
        return # Sensors do not receive messages

    def _send(self, msg: SensorMessage):
        if msg == self._current_msg:
            self._t.cancel() # Abort repeated (old) message and send new message
            self._tx_count = 0
            self._inc()
        if self._tx_count < 2: # Send up to three messages (first is immediate, subsequent 2 seconds apart unless aborted)
            sequence = self.sequence
            super()._send(msg)
            sequence = self.sequence
            self._t = Timer(2, self._send, [msg])
        else:
            self._tx_count = 0
            self._inc()

# Level 4

class KeychainRemote(Sensor):

    def panic(self):
        self._send(KeychainRemoteMessage(self.sn, self.sequence, KeychainRemoteMessage.EventType.PANIC))

    def away(self):
        self._send(KeychainRemoteMessage(self.sn, self.sequence, KeychainRemoteMessage.EventType.AWAY))

    def off(self):
        self._send(KeychainRemoteMessage(self.sn, self.sequence, KeychainRemoteMessage.EventType.OFF))


class PanicButton(Sensor):

    def press(self):
        self._send(PanicButtonMessage(self.sn, self.sequence, PanicButtonMessage.EventType.BUTTON_PRESS))


class MotionSensor(Sensor):

    def heartbeat(self):
        self._send(MotionSensorMessage(self.sn, self.sequence, MotionSensorMessage.EventType.HEARTBEAT))

    def trip(self):
        self._send(MotionSensorMessage(self.sn, self.sequence, MotionSensorMessage.EventType.MOTION))


class EntrySensor(Sensor):

    def open(self):
        self._send(EntrySensorMessage(self.sn, self.sequence, EntrySensorMessage.EventType.OPEN))

    def close(self):
        self._send(EntrySensorMessage(self.sn, self.sequence, EntrySensorMessage.EventType.CLOSED))


class GlassbreakSensor(Sensor):

    def heartbeat(self):
        self._send(GlassbreakSensorMessage(self.sn, self.sequence, GlassbreakSensorMessage.EventType.HEARTBEAT))

    def trip(self):
        self._send(GlassbreakSensorMessage(self.sn, self.sequence, GlassbreakSensorMessage.EventType.GLASSBREAK))

    def test(self):
        self._send(GlassbreakSensorMessage(self.sn, self.sequence, GlassbreakSensorMessage.EventType.GLASSBREAK_TEST))


class SmokeDetector(Sensor):

    def heartbeat(self):
        self._send(SmokeDetectorMessage(self.sn, self.sequence, SmokeDetectorMessage.EventType.HEARTBEAT))

    def trip(self):
        self._send(SmokeDetectorMessage(self.sn, self.sequence, SmokeDetectorMessage.EventType.SMOKE))
