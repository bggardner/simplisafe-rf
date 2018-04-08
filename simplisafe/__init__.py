from enum import unique, Enum, IntEnum

@unique
class UniqueEnum(Enum):

    @classmethod
    def key(cls, value):
        try:
          return list(cls.__members__.keys())[list(cls.__members__.values()).index(value)]
        except ValueError:
          return "Value does not exist in " + str(cls) + ": 0x{:02X}".format(value)


class UniqueIntEnum(IntEnum, UniqueEnum):
    pass


class DeviceType(UniqueIntEnum):

    BASE_STATION = 0
    KEYPAD = 1
    KEYCHAIN_REMOTE = 2
    PANIC_BUTTON = 3
    MOTION_SENSOR = 4
    ENTRY_SENSOR = 5
    GLASSBREAK_SENSOR = 6
    CO_DETECTOR = 7
    SMOKE_DETECTOR = 8
    WATER_SENSOR = 9
    FREEZE_SENSOR = 10


class ArmedState(UniqueIntEnum):

    OFF = 0x0
    ARMED_AWAY = 0x1
    ARMED_HOME = 0x2
    ARMING_AWAY = 0x3
    #ARMING_HOME = 0x4


class Validator:

    @staticmethod
    def pin(pin):
        pin = str(pin)
        try:
            int(pin)
        except ValueError:
            raise ValueError("PIN must be numeric")
        if len(pin) != 4:
            raise ValueError("PIN must be 4 digits")
        return pin

    @staticmethod
    def prefix(prefix):
        if prefix is None:
            return None
        prefix = str(prefix)
        try:
            int(prefix)
        except ValueError:
            raise Exception("Prefix must be numeric")
        if len(prefix) != 1:
            raise Exception("Prefix must be 1 digit")
        prefix = int(prefix)
        return prefix
