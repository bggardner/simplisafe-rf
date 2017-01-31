#!/usr/bin/python3
from enum import IntEnum, unique
import struct

class SerialNumberFormat:
    ASCII_4B5C = "4-byte-encoded 5-alphanumeric-character serial number"
    HEX_5B6C = "5-byte-encoded 6-hexadecimal-character serial number"

    @classmethod
    def unpack(cls, fmt: str, buffer: bytes):
        if fmt == cls.ASCII_4B5C:
            if len(buffer) < 4:
                raise ValueError
            b = [((buffer[2] >> 0) & 0x30) | (buffer[0] & 0xF)]
            b.append(((buffer[2] >> 2) & 0x30) | (buffer[0] >> 4))
            b.append(((buffer[3] << 4) & 0x30) | (buffer[1] & 0xF))
            b.append(((buffer[3] << 2) & 0x30) | (buffer[1] >> 4))
            b.append(((buffer[3] << 0) & 0x30) | (buffer[2] & 0xF))
            sn = ""
            for c in b:
                if c == 0x3F: # Blank
                    break
                sn += chr(c + 0x30)
            hb = bool(buffer[3] & 0x80)
            lb = bool(buffer[3] & 0x40)
            sn = (sn, hb, lb)
        elif fmt == cls.HEX_5B6C:
            if len(buffer) < 5:
                raise ValueError
            sn  = "{:X}".format(buffer[0] & 0xF)
            sn += "{:X}".format(buffer[1] & 0xF)
            sn += "{:X}".format(buffer[2] & 0xF)
            sn += "{:X}".format(buffer[3] & 0xF)
            sn += "{:X}".format(buffer[4] & 0xF)
            sn += "{:X}".format(buffer[3] >> 4)
        else:
            raise ValueError
        return sn

    @classmethod
    def pack(cls, fmt, s: str, hb: bool=False, lb: bool=False) -> bytes:
        if fmt == cls.ASCII_4B5C:
            b = []
            for i in range(5):
                if i < len(s):
                    b.append(ord(s[i]) - 0x30)
                else:
                    b.append(0x3F) # Blank
            buffer  = bytes([((b[1] & 0x0F) << 4) | (b[0] & 0xF)])
            buffer += bytes([((b[3] & 0x0F) << 4) | (b[2] & 0xF)])
            buffer += bytes([((b[1] & 0x30) << 2) | ((b[0] & 0x30) << 0) | (b[4] & 0x0F)])
            buffer += bytes([(int(hb) << 7 ) | (int(lb) << 6) | ((b[4] & 0x30) << 0) | ((b[3] & 0x30) >> 2) | ((b[2] & 0x30) >> 4)])
        elif fmt == cls.HEX_5B6C:
            buffer  = bytes([int(s[0], 16)])
            buffer += bytes([int(s[1], 16)])
            buffer += bytes([int(s[2], 16)])
            buffer += bytes([(int(s[5], 16) << 4) + int(s[3], 16)])
            buffer += bytes([int(s[4], 16)])
        else:
            raise ValueError
        return buffer


class InvalidMessageBytesError(ValueError):
    pass


@unique
class UniqueEnum(IntEnum):

    @classmethod
    def key(cls, value):
        try:
          return list(cls.__members__.keys())[list(cls.__members__.values()).index(value)]
        except ValueError:
          return "Value does not exist in " + str(cls) + ": 0x{:02X}".format(value)


# Level 1
class Message:

    PAYLOAD_LENGTHS = {0x00: 7, 0x11: 2, 0x22: 3, 0x33: 4, 0x66: 7}
    VENDOR_CODE = 0xCC05

    class OriginType(UniqueEnum):
        BASE_STATION = 0x0
        KEYPAD = 0x1
        KEYCHAIN_REMOTE = 0x2
        MOTION_SENSOR = 0x4
        ENTRY_SENSOR = 0x5

    def __init__(self, plc: int, sn: str, payload: bytes, footer: bytes):
        if len(sn) != 5:
            raise ValueError("Serial number must be 5 characters.") # TODO: Need to test for SNs less than 5 chars
        self.plc = plc
        self.sn = sn
        self.payload = payload
        self.footer = footer

    def __bytes__(self):
        sn = self.sn.encode('ascii')
        pl = Message.PAYLOAD_LENGTHS.get(self.plc)
        return struct.pack(">HB5B", self.VENDOR_CODE, self.plc, *sn) + self.payload + struct.pack(">B", self.checksum) + self.footer

    def __str__(self):
        s = "Payload Length Code: 0x{:02X} ({} bytes)\n".format(self.plc, self.PAYLOAD_LENGTHS.get(self.plc))
        s += "Serial Number: " + self.sn + "\n"
        s += "Checksum: 0x{:02X}\n".format(self.checksum)
        return s

    @property
    def checksum(self):
        return sum(self.payload) % 256

    @checksum.setter
    def checksum(self, value):
        if value != self.checksum:
            raise ValueError("Checksum mismatch! Received: 0x{:02X}, Calculated: 0x{:02X}".format(value, self.checksum))

    @classmethod
    def factory(cls, b: bytes, recurse: bool=True):
        if len(b) < 9:
            raise InvalidMessageBytesError("Message must be at least 9 bytes") # Consider removing or moving down to children
        vc = struct.unpack(">H", b[0:2])[0]
        if vc != Message.VENDOR_CODE:
            raise InvalidMessageBytesError("Invalid Vendor Code: 0x{:04X}".format(vc))
        plc = b[2]
        if plc not in cls.PAYLOAD_LENGTHS:
            raise InvalidMessageBytesError("Unknown payload length code: 0x{:02X}".format(plc))
        sn = b[3:8].decode('ascii')
        pl = cls.PAYLOAD_LENGTHS[plc]
        payload = b[8 : 8 + pl]
        footer = b[8 + pl + 1 :]
        msg = cls(plc, sn, payload, footer)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    msg = c.factory(msg)
                    break
                except ValueError:
                    pass
        checksum = b[8 + pl]
        msg.checksum = checksum # Validate checksum        
        return msg

# Level 2
class ComponentMessage(Message):

    @classmethod
    def factory(cls, msg: Message, recurse: bool=True):
        msg = cls(msg.plc, msg.sn, msg.payload, msg.footer)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise ValueError
        return msg


# Level 3
class KeypadMessage(ComponentMessage):

    footer = bytes()
    origin_type = Message.OriginType.KEYPAD

    class EventType(UniqueEnum):
        EXTENDED_STATUS_REQUEST = 0x11
        TEST_MODE_ON_REQUEST = 0x13
        EXTENDED_STATUS_REMOTE_UPDATE = 0x14
        ENTRY_SENSOR_UPDATE = 0x27
        EXTENDED_STATUS_UPDATE = 0x28
        STATUS_UPDATE = 0x31
        SENSOR_ERROR_1_UPDATE = 0x32
        SENSOR_ERROR_2_UPDATE = 0x35
        SENSOR_ERROR_3_UPDATE = 0x36
        SENSOR_ERROR_4_UPDATE = 0x37
        REMOVE_COMPONENT_MENU_REQUEST = 0x44 # Response is REMOVE_COMPONENT_SCROLL
        REMOVE_COMPONENT_SCROLL_MENU_REQUEST = 0x45 # Response is one of REMOVE_*_SCROLL below:
        REMOVE_ENTRY_SENSOR_SCROLL_MENU_REQUEST = 0x47
        REMOVE_MOTION_SENSOR_SCROLL_MENU_REQUEST = 0x48
        REMOVE_PANIC_BUTTON_SCROLL_MENU_REQUEST = 0x49
        REMOVE_KEYPAD_SCROLL_MENU_REQUEST = 0x4A
        REMOVE_KEYCHAIN_REMOTE_SCROLL_MENU_REQUEST = 0x4B
        REMOVE_GLASSBREAK_SENSOR_SCROLL_MENU_REQUEST = 0x4C
        REMOVE_SMOKE_DETECTOR_SCROLL_MENU_REQUEST = 0x4D
        REMOVE_CO_DETECTOR_SCROLL_MENU_REQUEST = 0x4E
        REMOVE_FREEZE_SENSOR_SCROLL_MENU_REQUEST = 0x4F
        REMOVE_WATER_SENSOR_SCROLL_MENU_REQUEST = 0x50
        DISARM_PIN_REQUEST = 0x51
        HOME_REQUEST = 0x53
        PANIC_REQUEST = 0x54
        AWAY_REQUEST = 0x56
        OFF_REMOTE_UPDATE = 0x57 # TODO: plc = 0x33, payload_body[0] = 0xFF, follows 'off' request by keychain or app
        OFF_REQUEST = 0x5C
        TEST_MODE_OFF_REQUEST = 0x5E
        ENTER_MENU_REQUEST = 0x61 # Verify request and response, including PLC and payload_body
        NEW_PIN_REQUEST = 0x62
        NEW_PREFIX_REQUEST = 0x63
        EXIT_MENU_REQUEST = 0x64
        MENU_PIN_REQUEST = 0x66
        REMOVE_COMPONENT_CONFIRM_MENU_REQUEST = 0x67
        ADD_ENTRY_SENSOR_MENU_REQUEST = 0x69
        ADD_MOTION_SENSOR_MENU_REQUEST = 0x6A
        ADD_PANIC_BUTTON_MENU_REQUEST = 0x6B
        ADD_KEYCHAIN_REMOTE_MENU_REQUEST = 0x6D
        ADD_GLASSBREAK_SENSOR_MENU_REQUEST = 0x6E
        ADD_SMOKE_DETECTOR_MENU_REQUEST = 0x6E
        CHANGE_PIN_MENU_REQUEST = 0x71
        CHANGE_PIN_CONFIRM_MENU_REQUEST = 0x72
        CHANGE_PREFIX_MENU_REQUEST = 0x73
        ADD_COMPONENT_MENU_REQUEST = 0x74
        ADD_COMPONENT_TYPE_MENU_REQUEST = 0x75
        REMOVE_COMPONENT_SELECT_MENU_REQUEST = 0x76
        ADD_COMPONENT_LAST_TYPE_MENU_REQUEST = 0x77 # Best guess, is sent three times
        ADD_CO_DETECTOR_MENU_REQUEST = 0x78
        ADD_FREEZE_SENSOR_MENU_REQUEST = 0x79
        ADD_WATER_SENSOR_MENU_REQUEST = 0x7A
        
    def __init__(self, plc: int, sn: str, sequence: int, event_type: 'KeypadMessage.EventType', payload_body: bytes):
        self.sequence = sequence
        self.event_type = event_type
        self.payload_body = payload_body
        super().__init__(plc, sn, self.payload, self.footer)

    def __str__(self):
        s = super().__str__()
        s += "Origin Type: " + self.origin_type.__class__.key(self.origin_type) + "\n"
        s += "Sequence: 0x{:X}\n".format(self.sequence)
        s += "Event Type: " + self.event_type.__class__.key(self.event_type) + "\n"
        return s

    @classmethod
    def factory(cls, msg: ComponentMessage, recurse: bool=True):
        origin_type = cls.OriginType(msg.payload[0])
        if origin_type != cls.origin_type:
            raise InvalidMessageBytesError
        sequence = msg.payload[1] >> 4
        payload_body = msg.payload[2:-1]
        event_type = cls.EventType(msg.payload[-1])
        msg = cls(msg.plc, msg.sn, sequence, event_type, payload_body)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise NotImplementedError("Unimplemented KeypadMessage, PLC: 0x{:02X}, Event Type: 0x{:02X}".format(msg.plc, event_type))
        return msg

    @property
    def payload(self):
        return bytes([self.origin_type, (self.sequence << 4) | 0x4]) + self.payload_body + bytes([self.event_type])

    @payload.setter
    def payload(self, value):
        if value != self.payload:
            raise ValueError


# This is a status message? (KE = 0x31)
#class KeypadOutOfRangeMessage(KeypadEventMessage):

#    def __init__(self, sn: str, sequence):
#        super().__init__(0x00, sn, AbstractKeypadEventRequest.EventType.OUT_OF_RANGE, sequence)

#    @KeypadEventMessage.payload.getter
#    def payload(self):
#        return self.payload_header + (self.sn[1:] + self.sn[0]).encode('ascii') + self.payload_footer

# Level 4
class KeypadRemoveComponentScrollMenuRequest(KeypadMessage):

    event_type = KeypadMessage.EventType.REMOVE_COMPONENT_SCROLL_MENU_REQUEST
    plc = 0x33

    def __init__(self, sn: str, sequence, n: int):
        self.n = n # TODO: Check range
        super().__init__(self.plc, sn, sequence, self.event_type, self.payload_body)

    def __str__(self):
        s = super().__str__()
        s += "Component Index: " + str(self.n) + "\n"
        return s

    @classmethod
    def factory(cls, msg: KeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        n = msg.payload_body[0]
        return cls(msg.sn, msg.sequence, n)

    @property
    def payload_body(self):
        return bytes([self.n])

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


class KeypadPinMessage(KeypadMessage):

    payload_body_suffix = bytes([0x0F, 0xF0])
    plc = 0x66

    def __init__(self, sn: str, sequence, event_type: 'KeypadMessage.EventType', pin):
        pin = str(pin)
        try:
            int(pin)
        except ValueError:
            raise ValueError("PIN must be numeric")
        if len(pin) != 4:
            raise ValueError("PIN must be 4 digits")
        self.pin = pin # ASCII
        super().__init__(self.plc, sn, sequence, event_type, self.payload_body)

    def __str__(self):
        s = super().__str__()
        s += "PIN: " + self.pin + "\n"
        return s

    @classmethod
    def factory(cls, msg: KeypadMessage, recurse: bool=True):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.payload_body[2:4] != cls.payload_body_suffix:
            raise InvalidMessageBytesError
        pin = str(msg.payload_body[0] & 0xF)
        pin += str(msg.payload_body[0] >> 4)
        pin += str(msg.payload_body[1] & 0xF)
        pin += str(msg.payload_body[1] >> 4)
        msg = cls(msg.sn, msg.sequence, msg.event_type, pin)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise InvalidMessageBytesError
        return msg

    @property
    def payload_body(self):
        stuffed_pin = bytes([(int(self.pin[1]) << 4) + int(self.pin[0]), (int(self.pin[3]) << 4) + int(self.pin[2])])
        return stuffed_pin + self.payload_body_suffix

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError

# Level 5
class KeypadDisarmPinRequest(KeypadPinMessage):

    event_type = KeypadMessage.EventType.DISARM_PIN_REQUEST

    def __init__(self, sn: str, sequence: int, pin):
        super().__init__(sn, sequence, self.event_type, pin)

    @classmethod
    def factory(cls, msg: KeypadPinMessage):
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence, msg.pin)


class KeypadNewPinRequest(KeypadPinMessage):

    event_type = KeypadMessage.EventType.NEW_PIN_REQUEST

    def __init__(self, sn: str, sequence: int, pin):
        super().__init__(sn, sequence, self.event_type, pin)

    @classmethod
    def factory(cls, msg: KeypadPinMessage):
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence, msg.pin)


class KeypadMenuPinRequest(KeypadPinMessage):

    event_type = KeypadMessage.EventType.MENU_PIN_REQUEST

    def __init__(self, sn: str, sequence: int, pin):
        super().__init__(sn, sequence, self.event_type, pin)

    @classmethod
    def factory(cls, msg: KeypadPinMessage):
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence, msg.pin)

# Level 4
class AbstractKeypadSimpleRequest(KeypadMessage):

    payload_body = bytes()
    plc = 0x22

    def __init__(self, sn: str, sequence: int):
        super().__init__(self.plc, sn, sequence, self.event_type, self.payload_body)

    @classmethod
    def factory(cls, msg: KeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        for c in cls.__subclasses__():
            if msg.event_type == c.event_type:
                return c(msg.sn, msg.sequence)
        raise InvalidMessageBytesError


# Level 5
class KeypadExtendedStatusRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.EXTENDED_STATUS_REQUEST


class KeypadTestModeOnRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.TEST_MODE_ON_REQUEST


class KeypadTestModeOffRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.TEST_MODE_OFF_REQUEST


class KeypadRemoveComponentMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.REMOVE_COMPONENT_MENU_REQUEST


class KeypadHomeRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.HOME_REQUEST


class KeypadPanicRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.PANIC_REQUEST


class KeypadAwayRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.AWAY_REQUEST


class KeypadOffRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.OFF_REQUEST


class KeypadEnterMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.ENTER_MENU_REQUEST


class KeypadExitMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.EXIT_MENU_REQUEST


class KeypadChangePinMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.CHANGE_PIN_MENU_REQUEST


class KeypadChangePinConfirmMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.CHANGE_PIN_CONFIRM_MENU_REQUEST


class KeypadAddComponentMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.ADD_COMPONENT_MENU_REQUEST


class KeypadRemoveComponentSelectMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.REMOVE_COMPONENT_SELECT_MENU_REQUEST


class KeypadAddComponentLastTypeMenuRequest(AbstractKeypadSimpleRequest):

    event_type = KeypadMessage.EventType.ADD_COMPONENT_LAST_TYPE_MENU_REQUEST


# Level 4
class KeypadPrefixRequest(KeypadMessage):

    event_type = KeypadMessage.EventType.NEW_PREFIX_REQUEST
    payload_body_prefix = "F"
    payload_body_suffix = "FFCFFF"
    plc = 0x66

    def __init__(self, sn: str, sequence: int, prefix):
        if prefix is not None:
            prefix = str(prefix)
            try:
                int(prefix)
            except ValueError:
                raise Exception("Prefix must be numeric")
            if len(prefix) != 1:
                raise Exception("Prefix must be 1 digit")
            prefix = int(prefix)
        self.prefix = prefix
        super().__init__(self.plc, sn, sequence, self.event_type, self.payload_body)

    def __str__(self):
        s = super().__str__()
        s += "Prefix: "
        if self.prefix is None:
            s += "(None)"
        else:
            s += str(self.prefix)
        s += "\n"
        return s

    @classmethod
    def factory(cls, msg: KeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        payload_body_prefix = "{:X}".format(msg.payload_body[0] >> 4)
        if payload_body_prefix != cls.payload_body_prefix:
            raise InvalidMessageBytesError
        payload_body_suffix = "{:02X}".format(msg.payload_body[1])
        if payload_body_suffix != cls.payload_body_suffix:
            raise InvalidMessageBytesError
        prefix = msg.payload_body[0] & 0xF
        if prefix == 0xF:
            prefix = None
        elif prefix > 9:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence, prefix)

    @property
    def payload_body(self):
        if self.prefix is None:
            prefix = 0xFFFFFFFF
        else:
            prefix = int(self.payload_body_prefix + str(self.prefix) + payload_body_suffix, 16)
        return struct.pack(">I", prefix)

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


class AbstractKeypadModifyComponentMenuRequest(KeypadMessage):

    plc = 0x66

    def __init__(self, sn: str, sequence: int, c_sn: str):
        # Verify if Component Type is sent
        self.c_sn = c_sn
        super().__init__(self.plc, sn, sequence, self.event_type, self.payload_body)

    def __str__(self):
        r = super().__str__()
        r += "Component Serial Number: " + self.c_sn + "\n"
        return r

    @classmethod
    def factory(cls, msg: KeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        (c_sn, hb, lb) = SerialNumberFormat.unpack(SerialNumberFormat.ASCII_4B5C, msg.payload_body)
        for c in cls.__subclasses__():
            if msg.event_type == c.event_type:
                return c(msg.sn, msg.sequence, c_sn)
        raise InvalidMessageBytesError

    @property
    def payload_body(self):
        if len(self.c_sn) == 5:
            return SerialNumberFormat.pack(SerialNumberFormat.ASCII_4B5C, self.c_sn)
        else:
            return SerialNumberFormat.pack(SerialNumberFormat.ASCII_4B5C, self.c_sn, True, True) # TODO: What makes these bits different?

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError

# Level 5
class KeypadRemoveComponentConfirmMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.REMOVE_COMPONENT_CONFIRM_MENU_REQUEST


class KeypadAddEntrySensorMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_ENTRY_SENSOR_MENU_REQUEST


class KeypadAddMotionSensorMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_MOTION_SENSOR_MENU_REQUEST


class KeypadAddPanicButtonMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_PANIC_BUTTON_MENU_REQUEST


class KeypadAddKeychainRemoteMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_KEYCHAIN_REMOTE_MENU_REQUEST


class KeypadAddGlassbreakSensorMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_GLASSBREAK_SENSOR_MENU_REQUEST


class KeypadAddSmokeDetectorMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_SMOKE_DETECTOR_MENU_REQUEST


class KeypadAddCoDetectorMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_CO_DETECTOR_MENU_REQUEST


class KeypadAddFreezeSensorMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_FREEZE_SENSOR_MENU_REQUEST


class KeypadAddWaterSensorMenuRequest(AbstractKeypadModifyComponentMenuRequest):

    event_type = KeypadMessage.EventType.ADD_WATER_SENSOR_MENU_REQUEST


# Level 4
class KeypadAddComponentTypeMenuRequest(KeypadMessage):

    event_type = KeypadMessage.EventType.ADD_COMPONENT_TYPE_MENU_REQUEST
    plc = 0x33

    class ComponentType(UniqueEnum):
        ENTRY_SENSOR = 0x00
        MOTION_SENSOR = 0x01
        PANIC_BUTTON = 0x02
        KEYPAD = 0x03
        KEYCHAIN_REMOTE = 0x04
        GLASSBREAK_SENSOR = 0x05
        CO_DETECTOR = 0x06
        SMOKE_DETECTOR = 0x07
        WATER_SENSOR = 0x08
        FREEZE_SENSOR = 0x09

    def __init__(self, sn: str, sequence, c_type: 'KeypadAddComponentTypeMenuRequest.ComponentType'):
        self.c_type = c_type
        super().__init__(self.plc, sn, sequence, self.event_type, self.payload_body)

    def __str__(self):
        s = super().__str__()
        s += "Component Type: " + self.c_type.__class__.key(self.c_type) + "\n"
        return s

    @classmethod
    def factory(cls, msg: KeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        c_type = KeypadAddComponentTypeMenuRequest.ComponentType(msg.payload_body[0])
        return cls(msg.sn, msg.sequence, c_type)

    @property
    def payload_body(self):
        return bytes([self.c_type])

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError

# Level 2
class BaseStationKeypadMessage(Message):

    origin_type = Message.OriginType.BASE_STATION

    class MessageType(UniqueEnum):
        RESPONSE = 0x01
        UPDATE = 0x05

    class InfoType(UniqueEnum):
        STATUS = 0x2
        MENU = 0x6

    def __init__(self, plc: int, kp_sn: str, sequence: int, msg_type: 'BaseStationKeypadMessage.MessageType', info_type: 'BaseStationKeypadMessage.InfoType', event_type: 'KeypadMessage.EventType', payload_body: bytes, footer_body: bytes):
        self.sequence = sequence
        self.msg_type = msg_type
        self.info_type = info_type
        self.event_type = event_type
        self.payload_body = payload_body
        self.footer_body = footer_body
        super().__init__(plc, kp_sn, self.payload, self.footer)

    def __str__(self):
        s = super().__str__()
        s += "Origin Type: " + self.origin_type.__class__.key(self.origin_type) + "\n"
        s += "Sequence: 0x{:X}\n".format(self.sequence)
        s += "Message Type: " + self.msg_type.__class__.key(self.msg_type) + "\n"
        s += "Info Type: " + self.info_type.__class__.key(self.info_type) + "\n"
        s += "Keypad Event Type: " + self.event_type.__class__.key(self.event_type) + "\n"
        s += "Footer Serial Number: " + SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, self.footer_body) + "\n"
        return s

    @classmethod
    def factory(cls, msg: Message, recurse: bool=True):
        origin_type = cls.OriginType(msg.payload[0])
        if origin_type != cls.origin_type:
            raise InvalidMessageBytesError
        msg_type = cls.MessageType(msg.payload[1])
        payload_body = msg.payload[2:-1]
        event_type = KeypadMessage.EventType(msg.payload[-1])
        sequence = msg.footer[5] >> 4
        info_type = cls.InfoType(msg.footer[5] & 0xF)
        #footer_sn = "{:X}".format(msg.footer[0] & 0xF)
        #footer_sn += "{:X}".format(msg.footer[1] & 0xF)
        #footer_sn += "{:X}".format(msg.footer[2] & 0xF)
        #footer_sn += "{:X}".format(msg.footer[3] & 0xF)
        #footer_sn += "{:X}".format(msg.footer[4] & 0xF)
        #footer_sn += "{:X}".format(msg.footer[3] >> 4)
        #footer_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer)
        footer_body = msg.footer[:-1]
        msg = cls(msg.plc, msg.sn, sequence, msg_type, info_type, event_type, payload_body, footer_body)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise NotImplementedError("Unimplemented BaseStationKeypadMessage, PLC: 0x{:02X}, Message Type: 0x{:02X}, Info Type: 0x{:02X}, Event Type: 0x{:02X}".format(msg.plc, msg_type, info_type, event_type))
        return msg

    @property
    def footer(self):
        return self.footer_body + bytes([(self.sequence << 4) | self.info_type])
        #footer = bytes([int(self.footer_sn[0], 16)])
        #footer += bytes([int(self.footer_sn[1], 16)])
        #footer += bytes([int(self.footer_sn[2], 16)])
        #footer += bytes([(int(self.footer_sn[5], 16) << 4) + int(self.footer_sn[3], 16)])
        #footer += bytes([int(self.footer_sn[4], 16)])
        #footer = SerialNumberFormat.pack(SerialNumberFormat.HEX_5B6C, self.footer_sn)
        #footer += bytes([(self.sequence << 4) | self.info_type])
        #return footer

    @footer.setter
    def footer(self, value):
        if value != self.footer:
            raise ValueError

    @property
    def payload(self):
        return bytes([self.origin_type, self.msg_type]) + self.payload_body + bytes([self.event_type])

    @payload.setter
    def payload(self, value):
        if value != self.payload:
            raise ValueError


# Level 3
class BaseStationKeypadResponseTrait:

    msg_type = BaseStationKeypadMessage.MessageType.RESPONSE


class BaseStationKeypadUpdateTrait:

    msg_type = BaseStationKeypadMessage.MessageType.UPDATE


class BaseStationKeypadStatusMessageTrait:

    info_type = BaseStationKeypadMessage.InfoType.STATUS

    class ErrorFlags(UniqueEnum):
        POWER_OUTAGE = 0
        ENTRY_SENSOR = 1
        UNKNOWN = 2 # TODO
        NO_LINK_TO_DISPATCHER = 3

    @property
    def footer_body(self):
        return SerialNumberFormat.pack(SerialNumberFormat.HEX_5B6C, self.bs_sn)

    @footer_body.setter
    def footer_body(self, value):
        if value != self.footer_body:
            raise ValueError


class BaseStationKeypadMenuMessageTrait:

    footer_body = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    info_type = BaseStationKeypadMessage.InfoType.MENU


class BaseStationKeypadExtendedStatusMessage(BaseStationKeypadMessage, BaseStationKeypadStatusMessageTrait):

    class ArmedStatusType(UniqueEnum):
        OFF = 0x0
        ARMED_AWAY = 0x1
        ARMED_HOME = 0x2
        ARMING_AWAY = 0x3
        ARMING_HOME = 0x4

    class EntrySensorStatusType(UniqueEnum):
        CLOSED = 0xF0
        OPEN = 0xF1

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, msg_type: 'BaseStationKeypadMessage.MessageType', event_type: 'KeypadRequest.EventType', flags: int, armed: 'BaseStationKeypadExtendedStatusMessage.ArmedStatusType', ess: 'BaseStationKeypadExtendedStatusMessage.EntrySensorStatusType', tl: int):
        self.bs_sn = bs_sn
        self.flags = flags
        self.armed = armed
        self.ess = ess
        self.tl = tl
        super().__init__(0x66, kp_sn, sequence, msg_type, self.info_type, event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += "Error Flags: \n"
        for i in BaseStationKeypadStatusMessageTrait.ErrorFlags:
            s += "\t" + i.__class__.key(i) + ": "
            if self.flags & (1 << i):
                s += "Y"
            else:
                s += "N"
            s += "\n"
        s += "Arm State: " + self.armed.__class__.key(self.armed) + "\n"
        s += "Entry Sensor Status: " + self.ess.__class__.key(self.ess) + "\n"
        s += "Countdown Timer: " + str(self.tl) + " seconds\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage, recurse: bool=True):
        if msg.plc != 0x66:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        flags = msg.payload_body[0] >> 4
        armed = cls.ArmedStatusType(msg.payload_body[0] & 0xF)
        ess = cls.EntrySensorStatusType(msg.payload_body[1])
        tl = (msg.payload_body[2] << 4) | (msg.payload_body[3] >> 4)
        msg = cls(msg.sn, msg.sequence, bs_sn, msg.msg_type, msg.event_type, flags, armed, ess, tl)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise NotImplementedError("Unimplemented BaseStationKeypadExtendedStatusMessage, Message Type: 0x{:02X}, Event Type: 0x{:02X}".format(msg.msg_type, msg.event_type))
        return msg

    @property
    def payload_body(self):
        payload_body = bytes([(self.flags << 4) | self.armed])
        payload_body += bytes([self.ess])
        payload_body += bytes([self.tl >> 4, ((self.tl & 0xF) << 4) | 0xC])
        return payload_body

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError

# Level 4
class BaseStationKeypadExtendedStatusResponse(BaseStationKeypadExtendedStatusMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.EXTENDED_STATUS_REQUEST

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, flags: int, armed: BaseStationKeypadExtendedStatusMessage.ArmedStatusType, ess: BaseStationKeypadExtendedStatusMessage.EntrySensorStatusType, tl: int):
        super().__init__(kp_sn, sequence, bs_sn, self.msg_type, self.event_type, flags, armed, ess, tl)

    @classmethod
    def factory(cls, msg: BaseStationKeypadExtendedStatusMessage):
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn, msg.flags, msg.armed, msg.ess, msg.tl)


class BaseStationKeypadExtendedStatusUpdate(BaseStationKeypadExtendedStatusMessage, BaseStationKeypadUpdateTrait):

    event_type = KeypadMessage.EventType.EXTENDED_STATUS_UPDATE

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, flags: int, armed: BaseStationKeypadExtendedStatusMessage.ArmedStatusType, ess: BaseStationKeypadExtendedStatusMessage.EntrySensorStatusType, tl: int):
        super().__init__(kp_sn, sequence, bs_sn, self.msg_type, self.event_type, flags, armed, ess, tl)

    @classmethod
    def factory(cls, msg: BaseStationKeypadExtendedStatusMessage):
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn, msg.flags, msg.armed, msg.ess, msg.tl)


class BaseStationKeypadExtendedStatusRemoteUpdate(BaseStationKeypadExtendedStatusMessage, BaseStationKeypadUpdateTrait):

    event_type = KeypadMessage.EventType.EXTENDED_STATUS_REMOTE_UPDATE

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, flags: int, armed: BaseStationKeypadExtendedStatusMessage.ArmedStatusType, ess: BaseStationKeypadExtendedStatusMessage.EntrySensorStatusType, tl: int):
        super().__init__(kp_sn, sequence, bs_sn, self.msg_type, self.event_type, flags, armed, ess, tl)

    @classmethod
    def factory(cls, msg: BaseStationKeypadExtendedStatusMessage):
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn, msg.flags, msg.armed, msg.ess, msg.tl)


# Level 3
class BaseStationKeypadStatusUpdate(BaseStationKeypadMessage, BaseStationKeypadUpdateTrait, BaseStationKeypadStatusMessageTrait):

    event_type = KeypadMessage.EventType.STATUS_UPDATE

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, flags: int):
        self.bs_sn = bs_sn
        self.flags = flags
        super().__init__(0x33, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += "Error Flags: \n"
        for i in BaseStationKeypadStatusMessageTrait.ErrorFlags:
            s += "\t" + i.__class__.key(i) + ": "
            if self.flags & (1 << i):
                s += "Y"
            else:
                s += "N"
            s += "\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != 0x33:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        flags = msg.payload_body[0]
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn, flags)

    @property
    def payload_body(self):
        return bytes([self.flags])

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


class BaseStationKeypadDisarmPinResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadStatusMessageTrait):

    event_type = KeypadMessage.EventType.DISARM_PIN_REQUEST

    class ResponseType(UniqueEnum):
        VALID = 0x4E
        INVALID = 0x01

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, response_type: ResponseType):
        self.bs_sn = bs_sn
        self.response_type = response_type
        super().__init__(0x33, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += "Response: " + self.response_type.__class__.key(self.response_type) + "\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage, recurse: bool=True):
        if msg.plc != 0x33:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != msg.event_type:
            raise InvalidMessageBytesError
        response_type = cls.ResponseType(msg.payload_body[0])
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        msg = cls(msg.sn, msg.sequence, bs_sn, response_type)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise NotImplementedError("Unimplemented BaseStationKeypadDisarmPinResponse: 0x{:02X}".format(response_type))
        return msg

    @property
    def payload_body(self):
        return bytes([self.response_type])

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


class BaseStationKeypadMenuPinResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadMenuMessageTrait):

    event_type = KeypadMessage.EventType.MENU_PIN_REQUEST

    class ResponseType(UniqueEnum):
        VALID = 0x00
        INVALID = 0x01

    def __init__(self, kp_sn: str, sequence: int, response_type: ResponseType):
        self.response_type = response_type
        super().__init__(0x33, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += "Response: " + self.response_type.__class__.key(self.response_type) + "\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage, recurse: bool=True):
        if msg.plc != 0x33:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        response_type = cls.ResponseType(msg.payload_body[0])
        msg = cls(msg.sn, msg.sequence, response_type)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise NotImplementedError("Unimplemented BaseStationKeypadMenuPinResponse: 0x{:02X}".format(response_type))
        return msg

    @property
    def payload_body(self):
        return bytes([self.response_type])

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


class BaseStationKeypadHomeResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadStatusMessageTrait):

    event_type = KeypadMessage.EventType.HOME_REQUEST
    payload_body = bytes([0x00]) # TODO: why constant?
    plc = 0x33

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str):
        self.bs_sn = bs_sn
        super().__init__(0x33, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn)


class BaseStationKeypadAwayResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadStatusMessageTrait):

    event_type = KeypadMessage.EventType.AWAY_REQUEST
    payload_body = bytes([0x78]) # TODO: why constant?
    plc = 0x33

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str):
        self.bs_sn = bs_sn
        super().__init__(0x33, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != 0x33:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != msg.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn)


class BaseStationKeypadOffRemoteUpdate(BaseStationKeypadMessage, BaseStationKeypadUpdateTrait, BaseStationKeypadStatusMessageTrait):

    event_type = KeypadMessage.EventType.OFF_REMOTE_UPDATE
    payload_body = bytes([0xFF]) # TODO: why constant?
    plc = 0x33

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str):
        self.bs_sn = bs_sn
        super().__init__(0x33, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != 0x33:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn)


class BaseStationKeypadEnterMenuResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadMenuMessageTrait):

    plc = 0x33
    event_type = KeypadMessage.EventType.ENTER_MENU_REQUEST
    payload_body = bytes([0x01]) # TODO: why constant?

    def __init__(self, kp_sn: str, sequence: int):
        super().__init__(0x33, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        if msg.footer_body != cls.footer_body:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence)


class BaseStationKeypadNewPrefixResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadMenuMessageTrait):

    event_type = KeypadMessage.EventType.NEW_PREFIX_REQUEST
    payload_body = bytes([0x00]) # TODO: See if keypad responds to other values (guessing anything other than 0x00 is "not accepted")
    plc = 0x33

    def __init__(self, kp_sn: str, sequence: int):
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        if msg.footer_body != cls.footer_body:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence)


class BaseStationKeypadRemoveComponentSelectResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadMenuMessageTrait):

    event_type = KeypadMessage.EventType.REMOVE_COMPONENT_SELECT_MENU_REQUEST
    payload_body = bytes([0x00]) # TODO: why constant?
    plc = 0x33

    def __init__(self, kp_sn: str, sequence: int):
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        if msg.footer_body != cls.footer_body:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence)


class BaseStationKeypadRemoveComponentConfirmMenuResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadMenuMessageTrait):

    event_type = KeypadMessage.EventType.REMOVE_COMPONENT_CONFIRM_MENU_REQUEST
    payload_body = bytes([0x00]) # TODO: why constant?
    plc = 0x33

    def __init__(self, kp_sn: str, sequence: int):
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        if msg.footer_body != cls.footer_body:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence)


class AbstractBaseStationKeypadAddComponentSerialMenuResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadMenuMessageTrait):

    plc = 0x33

    class ResponseType(UniqueEnum):
        SENSOR_ADDED = 0x00
        SENSOR_ALREADY_ADDED = 0x01

    def __init__(self, kp_sn: str, sequence: int, response_type: 'AbstractBaseStationKeypadAddComponentSerialMenuResponse.ResponseType'):
        self.response_type = response_type
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += 'Response Type: ' + self.response_type.__class__.key(self.response_type) + "\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.footer_body != cls.footer_body:
            raise InvalidMessageBytesError
        response_type = cls.ResponseType(msg.payload_body[0])
        for c in cls.__subclasses__():
            if msg.event_type == c.event_type:
                return c(msg.sn, msg.sequence, response_type)
        raise InvalidMessageBytesError

    @property
    def payload_body(self):
        return bytes([self.response_type])

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


class BaseStationKeypadAddEntrySensorMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_ENTRY_SENSOR_MENU_REQUEST


class BaseStationKeypadAddMotionSensorMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_MOTION_SENSOR_MENU_REQUEST


class BaseStationKeypadAddPanicButtonMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_PANIC_BUTTON_MENU_REQUEST


class BaseStationKeypadAddKeychainRemoteMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_KEYCHAIN_REMOTE_MENU_REQUEST


class BaseStationKeypadAddGlassbreakSensorMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_GLASSBREAK_SENSOR_MENU_REQUEST


class BaseStationKeypadAddSmokeDetectorMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_SMOKE_DETECTOR_MENU_REQUEST


class BaseStationKeypadAddCoDetectorMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_CO_DETECTOR_MENU_REQUEST


class BaseStationKeypadAddFreezeSensorMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_FREEZE_SENSOR_MENU_REQUEST


class BaseStationKeypadAddWaterSensorMenuResponse(AbstractBaseStationKeypadAddComponentSerialMenuResponse):

    event_type = KeypadMessage.EventType.ADD_WATER_SENSOR_MENU_REQUEST


class BaseStationKeypadSimpleMessageTrait:

    plc = 0x22
    payload_body = bytes()


class AbstractBaseStationKeypadSimpleStatusMessage(BaseStationKeypadMessage, BaseStationKeypadSimpleMessageTrait, BaseStationKeypadStatusMessageTrait):

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str):
        self.bs_sn = bs_sn
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        for c in cls.__subclasses__():
            if msg.msg_type == c.msg_type and msg.info_type == c.info_type and msg.event_type == c.event_type:
                return c(msg.sn, msg.sequence, bs_sn)
        raise InvalidMessageBytesError


class AbstractBaseStationKeypadSimpleMenuMessage(BaseStationKeypadMessage, BaseStationKeypadSimpleMessageTrait, BaseStationKeypadMenuMessageTrait):

    def __init__(self, kp_sn: str, sequence: int):
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.payload_body != cls.payload_body:
            raise InvalidMessageBytesError
        for c in cls.__subclasses__():
            if msg.msg_type == c.msg_type and msg.info_type == c.info_type and msg.event_type == c.event_type and msg.footer_body == c.footer_body:
                return c(msg.sn, msg.sequence)
        raise InvalidMessageBytesError


#Level 4
class BaseStationKeypadTestModeOnResponse(AbstractBaseStationKeypadSimpleStatusMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.TEST_MODE_ON_REQUEST


class BaseStationKeypadOffResponse(AbstractBaseStationKeypadSimpleStatusMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.OFF_REQUEST


class BaseStationKeypadTestModeOffResponse(AbstractBaseStationKeypadSimpleStatusMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.TEST_MODE_OFF_REQUEST


class BaseStationKeypadExitMenuResponse(AbstractBaseStationKeypadSimpleMenuMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.EXIT_MENU_REQUEST


class BaseStationKeypadChangePinMenuResponse(AbstractBaseStationKeypadSimpleMenuMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.CHANGE_PIN_MENU_REQUEST


class BaseStationKeypadChangePinConfirmMenuResponse(AbstractBaseStationKeypadSimpleMenuMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.CHANGE_PIN_CONFIRM_MENU_REQUEST


class BaseStationKeypadChangePrefixMenuResponse(AbstractBaseStationKeypadSimpleMenuMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.CHANGE_PREFIX_MENU_REQUEST


class BaseStationKeypadAddComponentMenuResponse(AbstractBaseStationKeypadSimpleMenuMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.ADD_COMPONENT_MENU_REQUEST


class BaseStationKeypadAddComponentTypeMenuResponse(AbstractBaseStationKeypadSimpleMenuMessage, BaseStationKeypadResponseTrait):

    event_type = KeypadMessage.EventType.ADD_COMPONENT_TYPE_MENU_REQUEST


class BaseStationKeypadClearSensorError1Update(AbstractBaseStationKeypadSimpleStatusMessage, BaseStationKeypadUpdateTrait):

    event_type = KeypadMessage.EventType.SENSOR_ERROR_1_UPDATE


class BaseStationKeypadClearSensorError2Update(AbstractBaseStationKeypadSimpleStatusMessage, BaseStationKeypadUpdateTrait):

    event_type = KeypadMessage.EventType.SENSOR_ERROR_2_UPDATE


class BaseStationKeypadClearSensorError3Update(AbstractBaseStationKeypadSimpleStatusMessage, BaseStationKeypadUpdateTrait):

    event_type = KeypadMessage.EventType.SENSOR_ERROR_3_UPDATE


class BaseStationKeypadClearSensorError4Update(AbstractBaseStationKeypadSimpleStatusMessage, BaseStationKeypadUpdateTrait):

    event_type = KeypadMessage.EventType.SENSOR_ERROR_4_UPDATE


# Level 3
class AbstractBaseStationKeypadRemoveComponentScrollMenuResponse(BaseStationKeypadMessage, BaseStationKeypadResponseTrait, BaseStationKeypadMenuMessageTrait):

    plc = 0x66

    def __init__(self, kp_sn: str, sequence: int, c_sn: str, left_arrow: bool, right_arrow: bool):
        self.c_sn = c_sn
        self.left_arrow = left_arrow
        self.right_arrow = right_arrow
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += "Component Serial Number: " + self.c_sn + "\n"
        s += "Left Arrow: " + ("Y" if self.left_arrow else "N") + "\n"
        s += "Right Arrow: " + ("Y" if self.right_arrow else "N") + "\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        (c_sn, left_arrow, right_arrow) = SerialNumberFormat.unpack(SerialNumberFormat.ASCII_4B5C, msg.payload_body)
        for c in cls.__subclasses__():
            if msg.event_type == c.event_type:
                return c(msg.sn, msg.sequence, c_sn, left_arrow, right_arrow)
        raise InvalidMessageBytesError

    @property
    def payload_body(self):
        payload_body = SerialNumberFormat.pack(SerialNumberFormat.ASCII_4B5C, self.c_sn, self.left_arrow, self.right_arrow)
        return payload_body

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


# Level 4
class BaseStationKeypadRemoveEntrySensorScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_ENTRY_SENSOR_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveMotionSensorScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_MOTION_SENSOR_SCROLL_MENU_REQUEST


class BaseStationKeypadRemovePanicButtonScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_PANIC_BUTTON_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveKeypadScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_KEYPAD_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveKeychainRemoteScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_KEYCHAIN_REMOTE_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveGlassbreakSensorScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_GLASSBREAK_SENSOR_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveSmokeDetectorScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_SMOKE_DETECTOR_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveCoDetectorScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_CO_DETECTOR_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveFreezeSensorScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_FREEZE_SENSOR_SCROLL_MENU_REQUEST


class BaseStationKeypadRemoveWaterSensorScrollMenuResponse(AbstractBaseStationKeypadRemoveComponentScrollMenuResponse):

    event_type = KeypadMessage.EventType.REMOVE_WATER_SENSOR_SCROLL_MENU_REQUEST


class BaseStationKeypadInvalidDisarmPinResponse(BaseStationKeypadDisarmPinResponse):

    response_type = BaseStationKeypadDisarmPinResponse.ResponseType.INVALID

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str):
        super().__init__(kp_sn, sequence, bs_sn, self.response_type)

    @classmethod
    def factory(cls, msg: BaseStationKeypadDisarmPinResponse):
        if msg.response_type != cls.response_type:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn)


class BaseStationKeypadValidDisarmPinResponse(BaseStationKeypadDisarmPinResponse):

    response_type = BaseStationKeypadDisarmPinResponse.ResponseType.VALID

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str):
        super().__init__(kp_sn, sequence, bs_sn, self.response_type)

    @classmethod
    def factory(cls, msg: BaseStationKeypadDisarmPinResponse):
        if msg.response_type != cls.response_type:
            raise InvalidMessageBytesError
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn)


class BaseStationKeypadInvalidMenuPinResponse(BaseStationKeypadMenuPinResponse):

    response_type = BaseStationKeypadMenuPinResponse.ResponseType.INVALID

    def __init__(self, kp_sn: str, sequence: int):
        super().__init__(kp_sn, sequence, self.response_type)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMenuPinResponse):
        if msg.response_type != cls.response_type:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence)


class BaseStationKeypadValidMenuPinResponse(BaseStationKeypadMenuPinResponse):

    response_type = BaseStationKeypadMenuPinResponse.ResponseType.VALID

    def __init__(self, kp_sn: str, sequence: int):
        super().__init__(kp_sn, sequence, self.response_type)

    @classmethod
    def factory(cls, msg: BaseStationKeypadMenuPinResponse):
        if msg.response_type != cls.response_type:
            raise InvalidMessageBytesError
        return cls(msg.sn, msg.sequence)


# Level 3
class BaseStationKeypadEntrySensorUpdate(BaseStationKeypadMessage, BaseStationKeypadUpdateTrait, BaseStationKeypadStatusMessageTrait):

    event_type = KeypadMessage.EventType.ENTRY_SENSOR_UPDATE
    plc = 0x33

    class UpdateType(UniqueEnum):
        CLOSED = 0x00
        OPEN = 0x01

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, ese: 'BaseStationKeypadEntrySensorUpdate.UpdateType'):
        self.bs_sn = bs_sn
        self.ese = ese
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, self.event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += "Entry Sensor Event: " + self.ese.__class__.key(self.ese) + "\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != cls.info_type:
            raise InvalidMessageBytesError
        if msg.event_type != cls.event_type:
            raise InvalidMessageBytesError
        ese = cls.UpdateType(msg.payload_body[0])
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn, ese)

    @property
    def payload_body(self):
        return bytes([self.ese])

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


class BaseStationKeypadSensorErrorUpdate(BaseStationKeypadMessage, BaseStationKeypadUpdateTrait, BaseStationKeypadStatusMessageTrait):

    plc = 0x66

    def __init__(self, kp_sn: str, sequence: int, bs_sn: str, n: int, c_sn: str):
        self.bs_sn = bs_sn
        self.c_sn = c_sn
        if n == 0:
            event_type = KeypadMessage.EventType.SENSOR_ERROR_1_UPDATE
        elif n == 1:
            event_type = KeypadMessage.EventType.SENSOR_ERROR_2_UPDATE
        elif n == 2:
            event_type = KeypadMessage.EventType.SENSOR_ERROR_3_UPDATE
        elif n == 3:
            event_type = KeypadMessage.EventType.SENSOR_ERROR_4_UPDATE
        else:
            raise Exception("Only 4 Sensor Errors are supported.")
        super().__init__(self.plc, kp_sn, sequence, self.msg_type, self.info_type, event_type, self.payload_body, self.footer_body)

    def __str__(self):
        s = super().__str__()
        s += "Sensor Serial Number: " + self.c_sn + "\n"
        return s

    @classmethod
    def factory(cls, msg: BaseStationKeypadMessage):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        if msg.msg_type != cls.msg_type:
            raise InvalidMessageBytesError
        if msg.info_type != msg.info_type:
            raise InvalidMessageBytesError
        if msg.event_type == KeypadMessage.EventType.SENSOR_ERROR_1_UPDATE:
            n = 0
        elif msg.event_type == KeypadMessage.EventType.SENSOR_ERROR_2_UPDATE:
            n = 1
        elif msg.event_type == KeypadMessage.EventType.SENSOR_ERROR_3_UPDATE:
            n = 2
        elif msg.event_type == KeypadMessage.EventType.SENSOR_ERROR_4_UPDATE:
            n = 3
        else:
            raise InvalidMessageBytesError
        (c_sn, hb, lb) = SerialNumberFormat.unpack(SerialNumberFormat.ASCII_4B5C, msg.payload_body)
        bs_sn = SerialNumberFormat.unpack(SerialNumberFormat.HEX_5B6C, msg.footer_body)
        return cls(msg.sn, msg.sequence, bs_sn, n, c_sn)

    @property
    def payload_body(self):
        return SerialNumberFormat.pack(SerialNumberFormat.ASCII_4B5C, self.c_sn)

    @payload_body.setter
    def payload_body(self, value):
        if value != self.payload_body:
            raise ValueError


# Level 3
class SensorMessage(ComponentMessage):

    footer = bytes()
    plc = 0x11

    class EventType(UniqueEnum):
        pass

    def __init__(self, sn: str, origin_type: Message.OriginType, sequence: int, event_type: 'SensorMessage.EventType'):
        self.origin_type = origin_type
        self.sequence = sequence
        self.event_type = event_type
        super().__init__(self.plc, sn, self.payload, self.footer)

    def __str__(self):
        r = super().__str__()
        r += "Origin Type: " + self.origin_type.__class__.key(self.origin_type) + "\n"
        r += "Event Type: " + self.event_type.__class__.key(self.event_type) + "\n"
        r += "Sequence: 0x{:X}".format(self.sequence) + "\n"
        return r

    @classmethod
    def factory(cls, msg: ComponentMessage, recurse: bool=True):
        if msg.plc != cls.plc:
            raise InvalidMessageBytesError
        origin_type = cls.OriginType(msg.payload[0] & 0xF)
        sequence = msg.payload[0] >> 4
        event_type = msg.payload[1]
        msg = cls(msg.sn, origin_type, sequence, event_type)
        if recurse:
            for c in cls.__subclasses__():
                try:
                    return c.factory(msg)
                except ValueError:
                    pass
            raise NotImplementedError("Unimplemented SensorMessage, Event: 0x{:02X}".format(event_type))

    @property
    def payload(self):
        stuffed_byte = (self.sequence << 4) + self.origin_type
        return bytes([stuffed_byte, self.event_type])

    @payload.setter
    def payload(self, value):
        if value != self.payload:
            raise ValueError


# Level 4
class KeychainRemoteMessage(SensorMessage):

    origin_type = Message.OriginType.KEYCHAIN_REMOTE

    class EventType(SensorMessage.EventType):
        PANIC = 0x01
        AWAY = 0x02
        OFF = 0x03

    def __init__(self, sn: str, sequence: int, event_type: 'KeychainRemoteMessage.EventType'):
        self.event_type = event_type
        super().__init__(sn, self.origin_type, sequence, event_type)

    @classmethod
    def factory(cls, msg: SensorMessage):
        if msg.origin_type != cls.origin_type:
            raise InvalidMessageBytesError
        event_type = KeychainRemoteMessage.EventType(msg.event_type)
        return cls(msg.sn, msg.sequence, event_type)

    
class MotionSensorMessage(SensorMessage):

    origin_type = Message.OriginType.MOTION_SENSOR

    class EventType(SensorMessage.EventType):
        HEARTBEAT = 0x00
        MOTION = 0x02

    def __init__(self, sn: str, sequence: int, event_type: 'MotionSensorMessage.EventType'):
        self.event_type = event_type
        super().__init__(sn, self.origin_type, sequence, event_type)

    @classmethod
    def factory(cls, msg: SensorMessage):
        if msg.origin_type != cls.origin_type:
            raise InvalidMessageBytesError
        event_type = MotionSensorMessage.EventType(msg.event_type)
        return cls(msg.sn, msg.sequence, event_type)


class EntrySensorMessage(SensorMessage):

    origin_type = Message.OriginType.ENTRY_SENSOR

    class EventType(SensorMessage.EventType):
        OPEN	= 0x01
        CLOSED	= 0x02

    def __init__(self, sn: str, sequence: int, event_type: 'EntrySensorMessage.EventType'):
        self.event_type = EntrySensorMessage.EventType(event_type)
        super().__init__(sn, self.origin_type, sequence, event_type)

    @classmethod
    def factory(cls, msg: SensorMessage):
        if msg.origin_type != cls.origin_type:
            raise InvalidMessageBytesError
        event_type = EntrySensorMessage.EventType(msg.event_type)
        return cls(msg.sn, msg.sequence, event_type)
