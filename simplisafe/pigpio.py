#!/usr/bin/python3

import os
import pigpio
from simplisafe import DeviceType
from simplisafe.messages import Message, BaseStationKeypadMessage, ComponentMessage, KeypadMessage, SensorMessage
from simplisafe.devices import AbstractTransceiver
import socket
from sys import stderr
from threading import Thread
from time import sleep

class DecodeError(Exception):
    pass

class Transceiver(AbstractTransceiver):

    def __init__(self, *args, **kwargs):

        if 'rx' in kwargs:
            self.is_receiver = True
            self.rx = kwargs['rx']
            del kwargs['rx']
        else:
            self.is_receiver = False

        if 'tx' in kwargs:
            self.is_transmitter = True
            self.tx = kwargs['tx']
            del kwargs['tx']
        else:
            self.is_transmitter = False

        if not self.is_receiver and not self.is_transmitter:
            raise ValueError("Receiver or Transmitter GPIO pin is required")

        self._read_fd, self._write_fd = os.pipe()

        self._pi = pigpio.pi(**kwargs) # Connect to pgpiod
        if self.is_receiver:
            self._pi.set_mode(self.rx, pigpio.INPUT)
            self._pi.set_glitch_filter(self.rx, 400)
            #self._pi.set_noise_filter(self.rx, 400, 400)
        if self.is_transmitter:
            self._pi.set_mode(self.tx, pigpio.OUTPUT)

        self._listener = Thread(target=self._listen)
        self._listener.start()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._listener.join(0)
        self._pi.stop() # Disconnect from pigpiod
        os.close(self._read_fd)
        os.close(self._write_fd)

    def _listen_cbf(self, gpio, level, tick):
        if self._rx_done:
            return
        if self._rx_t is None:
            self._rx_t = tick
            return # First edge
        if self._rx_t > tick:
            dt = ((tick << 32) - self._rx_t) / 1000 # Tick overflow
        else:
            dt = (tick - self._rx_t) / 1000 # Convert to ms
        self._rx_t = tick
        if dt > 2.1:
            if self._rx_preamble_high:
                self._rx_done = True # End of transmission
            else:
                self._rx_start_flag0 = False # Malformed
            return
        if dt > 1.9:
            if self._rx_sync_buffer == '1111': # Check for at least 2 SYNC periods
                if level == 1:
                    self._rx_preamble_low = True # Valid preamble low pulse
                    self._rx_preamble_high = False
                elif self._rx_preamble_low:
                    self._rx_preamble_high = True # Valid preamble high pulse
                    self._rx_buffer = '' # Data follows preamble
            else:
                self._rx_preamble_low = False
            return
        if dt > 1.1:
            bit = 'X' # Invalid duration
        elif dt >= 0.9:
            bit = '1'
        elif dt > 0.6:
            bit = 'X' # Invalid duration
        else:
            bit = '0'
        self._rx_sync_buffer += bit # Append SYNC buffer
        self._rx_sync_buffer = self._rx_sync_buffer[-4:] # Limit SYNC buffer to 2 periods
        if self._rx_preamble_high:
            self._rx_buffer += bit # Append buffer
        else:
            self._rx_buffer = '' # Don't append buffer if no valid preamble

    def _listen(self):
        if not self.is_receiver:
            raise RuntimeError("Receiver not configured")
        while True:
            self._rx_done = False
            self._rx_buffer = ''
            self._rx_t = None
            self._rx_preamble_low = False
            self._rx_preamble_high = False
            self._rx_sync_buffer = ''
            cb = self._pi.callback(self.rx, pigpio.EITHER_EDGE, self._listen_cbf)
            while not self._rx_done:
                pass
            cb.cancel()
            try:
                decoded = self.decode(self._rx_buffer)
                #print("Raw: " + "".join(map("{:02X}".format, decoded)))
            except DecodeError as e:
                print(str(e), file=stderr)
                continue
            os.write(self._write_fd, decoded)

    @staticmethod
    def decode(bits: str) -> bytes:
        if bits.count('X') != 0:
            raise DecodeError('Message ignored (bad pulse width in {:d} bits): '.format(bits.count('X')) + bits)
                
        raw_hex = ''
        for i in range(0, len(bits), 4):
            nibble = "{:X}".format(int(bits[i:i+4][::-1], 2)) # Zero-fill of partial nibbles
            raw_hex += nibble

        try:
            origin = DeviceType(int(raw_hex[16], 16))
        except:
            raise DecodeError('Invalid origin: [' + raw_hex[16:18][::-1] + '], Raw: ' + raw_hex);

        if origin == DeviceType.BASE_STATION:
            unswapped = raw_hex[:-2] # Strip end delimeter
        else:
            rd = raw_hex.find('F' + raw_hex[0:4])
            unswapped = raw_hex[:rd] # Strip end delimeter and repeated sequence
        if len(unswapped) % 2 == 1:
            raise DecodeError('Message ignored (odd byte count: ' + str(len(unswapped)) + ')')

        swapped = bytes()
        for i in range(0, len(unswapped), 2):
            swapped += bytes([int(unswapped[i + 1] + unswapped[i], 16)]) # Swap nibbles and convert to bytes
        return swapped

    def fileno(self):
        return self._read_fd

    def recv(self):
        return Message.factory(os.read(self._read_fd, 24))

    def send(self, msg: Message, mode='script'):

        if not self.is_transmitter:
            raise RuntimeError("Transmitter is not configured")

        if mode == 'wave':
            f = self.send_wave
        elif mode == 'script':
            f = self.send_script
        else:
            raise ValueError

        # TODO: This should be handled at an upper layer, as the triple transmission will end if a sensor state changes before completion
        if isinstance(msg, SensorMessage):
            for i in range(3):
                f(msg)
                sleep(2)
        else:
            f(msg)
        print("Message transmitted.")

    def send_wave(self, msg: Message):
        w = []
        if isinstance(msg, BaseStationKeypadMessage):
            syncs = 150
        elif isinstance(msg, KeypadMessage):
            syncs = 40
        elif isinstance(msg, SensorMessage):
            syncs = 20
        else:
            raise TypeError
        next_bit = 0
        for i in range(syncs):
            w.append(pigpio.pulse(0, self.tx, 1000))
            w.append(pigpio.pulse(self.tx, 0, 1000))
        wd = []
        wd.append(pigpio.pulse(0, self.tx, 2000))
        wd.append(pigpio.pulse(self.tx, 0, 2000))
        next_bit = 0
        for msg_byte in bytes(msg):
            for i in range(8):
                if msg_byte & (1 << i):
                    d = 1000
                else:
                    d = 500
                if next_bit == 1:
                    wd.append(pigpio.pulse(self.tx, 0, d))
                else:
                    wd.append(pigpio.pulse(0, self.tx, d))
                next_bit ^= 1    
        if isinstance(msg, BaseStationKeypadMessage):
            ds = [1000, 1000, 500, 500]
            for d in ds:
                if next_bit == 1:
                    wd.append(pigpio.pulse(self.tx, 0, d))
                else:
                    wd.append(pigpio.pulse(0, self.tx, d))
                next_bit ^= 1
        for i in range(4):
            if next_bit == 1:
                wd.append(pigpio.pulse(self.tx, 0, 1000))
            else:
                wd.append(pigpio.pulse(0, self.tx, 1000))
            next_bit ^= next_bit
        if isinstance(msg, BaseStationKeypadMessage):
            ws = []
            for i in range(18):
                ws.append(pigpio.pulse(0, self.tx, 1000))
                ws.append(pigpio.pulse(self.tx, 0, 1000))
            w = w + wd + ws + wd + ws + wd
        elif isinstance(msg, ComponentMessage):
            w = w + wd + wd
        else:
            raise TypeError
        self._pi.wave_clear()
        self._pi.wave_add_generic(w)
        wid = self._pi.wave_create()
        if wid < 0:
            raise Exception("Message wave creation failed!")
        self._pi.wave_send_once(wid)
        while self._pi.wave_tx_busy():
            sleep(1)
        self._pi.wave_clear()
        self._pi.stop()

    def send_script(self, msg: Message):
        s = []
        if isinstance(msg, BaseStationKeypadMessage):
            s.append("ld v0 150 tag 0 w " + str(self.tx) + " 0 mics 1000 w " + str(self.tx) + " 1 mics 1000 dcr v0 jp 0")
        elif isinstance(msg, KeypadMessage):
            s.append("ld v0 40 tag 0 w " + str(self.tx) + " 0 mics 1000 w " + str(self.tx) + " 1 mics 1000 dcr v0 jp 0")
        elif isinstance(msg, SensorMessage):
            s.append("ld v0 20 tag 0 w " + str(self.tx) + " 0 mics 1000 w " + str(self.tx) + " 1 mics 1000 dcr v0 jp 0")
        else:
            raise TypeError
        preamble = "w " + str(self.tx) + " 0 mics 2000 w " + str(self.tx) + " 1 mics 2000"
        s.append(preamble)
        next_bit = 0
        for msg_byte in bytes(msg):
            for i in range(8):
                s_i = "w " + str(self.tx) + " " + str(next_bit) + " mics "
                if msg_byte & (1 << i):
                    s_i += "1000"
                else:
                    s_i += "500"
                s.append(s_i)
                next_bit ^= 1
        if isinstance(msg, BaseStationKeypadMessage):
            s.append("w " + str(self.tx) + " " + str(next_bit) + " mics 1000")
            s.append("w " + str(self.tx) + " " + str(next_bit) + " mics 1000")
            s.append("w " + str(self.tx) + " " + str(next_bit) + " mics 500")
            s.append("w " + str(self.tx) + " " + str(next_bit) + " mics 500")
            next_bit ^= 1
        for i in range(4):
            s.append("w " + str(self.tx) + " " + str(next_bit) + " mics 1000")
            next_bit ^= 1
        sd = s[1:]
        if isinstance(msg, BaseStationKeypadMessage):
            s.append("ld v0 18 tag 1 w " + str(self.tx) + " " + str(next_bit) + " mics 1000 w " + str(self.tx) + " " + str(next_bit) + " mics 1000 dcr v0 jp 1")
            next_bit ^= 1
            s = s + sd
            s.append("ld v0 18 tag 2 w " + str(self.tx) + " " + str(next_bit) + " mics 1000 w " + str(self.tx) + " " + str(next_bit) + " mics 1000 dcr v0 jp 2")
            next_bit ^= 1
            s = s + sd
        elif isinstance(msg, ComponentMessage):
            s = s + sd
        else:
            raise TypeError
        s.append("w " + str(self.tx) + " 0")
        sid = self._pi.store_script(bytes(" ".join(s), 'ascii'))
        if sid < 0:
            raise Exception("Script failed to store!")
        self._pi.run_script(sid)
        while True:
            (s, _) = self._pi.script_status(sid)
            if s == pigpio.PI_SCRIPT_FAILED:
                raise Exception("Message send script failed!")
            elif s == pigpio.PI_SCRIPT_HALTED:
                self._pi.delete_script(sid)
                break
