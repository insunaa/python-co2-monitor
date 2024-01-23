import usb.core
import usb.util
import threading
import time

class CO2Monitor:
    def __init__(self, vid=0x04d9, pid=0xa052):
        self._vid = vid
        self._pid = pid
        # Random key buffer.
        self._key = bytes([0xc4, 0xc6, 0xc0, 0x92, 0x40, 0x23, 0xdc, 0x96])

        self._device = None
        self._endpoint = None

        self._co2 = None
        self._temp = None
        self._hum = None

    def connect(self):
        self._device = usb.core.find(idVendor=self._vid, idProduct=self._pid)
        if not self._device:
            raise RuntimeError("Device not found!")
        try:
            # Detach kernel driver on Linux
            if self._device.is_kernel_driver_active(0):
                self._device.detach_kernel_driver(0)

            bmReqType = 0x21
            bReq = 0x09
            wValue = 0x0300
            wIdx = 0x00

            self._device.ctrl_transfer(bmReqType, bReq, wValue, wIdx, self._key)

            # Claim interface
            self._interface = self._device.get_active_configuration()[(0, 0)]
            usb.util.claim_interface(self._device, self._interface.bInterfaceNumber)

            # Set up the endpoint
            self._endpoint = self._interface[0]
            print("Connection Established")

        except Exception as e:
            print(f"Connect Exception: {e}")

    def disconnect(self):
        if self._device.is_kernel_driver_active(0):
            self._device.attach_kernel_driver(0)
        usb.util.release_interface(self._device, self._interface)
        usb.util.dispose_resources(self._device)

    def transfer(self):
        def data_transfer():
            while True:
                try:
                    data = self._endpoint.read(8, timeout=1000)
                    self._process_data(data)
                except usb.core.USBError as e:
                    if e.errno == 110:
                        time.sleep(1)
                        continue
                    print(f"USB Error: {e}")
                    break
                except Exception as e:
                    disconnect()
                    print(f".Error: {e}")
        data_transfer()

    def on_temp(self, callback):
        self._on_temp_callback = callback

    def on_co2(self, callback):
        self._on_co2_callback = callback

    def on_hum(self, callback):
        self._on_hum_callback = callback

    def on_error(self, callback):
        self._on_error_callback = callback

    def _process_data(self, data):
        # Skip decryption for modern CO2 sensors.
        if data[4] != 0x0d:
            data = self._decrypt(self._key, data)

        checksum = data[3]
        calculated_sum = sum(data[:3]) & 0xff

        if data[4] != 0x0d or checksum != calculated_sum:
            self._on_error_callback(RuntimeError("Checksum Error"))
            return

        op = data[0]
        value = (data[1] << 8) | data[2]

        if op == 0x42:
            self._temp = (value / 16) - 273.15
            self._on_temp_callback(self._temp)
        elif op == 0x50:
            self._co2 = value
            self._on_co2_callback(self._co2)
        elif op == 0x41:
            self._hum = value / 100
            self._on_hum_callback(self._hum)

    @staticmethod
    def _decrypt(key, data):
        cstate = [0x48, 0x74, 0x65, 0x6D, 0x70, 0x39, 0x39, 0x65]
        shuffle = [2, 4, 0, 7, 1, 6, 5, 3]
        length = len(cstate)

        data_xor = [0] * length
        for i in range(length):
            idx = shuffle[i]
            data_xor[idx] = data[i] ^ key[idx]

        data_tmp = [0] * length
        for i in range(length):
            data_tmp[i] = ((data_xor[i] >> 3) | (data_xor[(i - 1 + 8) % 8] << 5)) & 0xff

        results = [0] * length
        for i in range(length):
            ctmp = ((cstate[i] >> 4) | (cstate[i] << 4)) & 0xff
            results[i] = ((0x100 + data_tmp[i] - ctmp) & 0xff)

        return bytes(results)

