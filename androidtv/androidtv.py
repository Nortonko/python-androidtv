"""Communicate with an Android TV device via ADB over a network.

ADB Debugging must be enabled.
"""


import logging
import re

from .basetv import BaseTV
from . import constants


# Regular expression patterns
BLOCK_REGEX_PATTERN = "STREAM_MUSIC(.*?)- STREAM"
DEVICE_REGEX_PATTERN = r"Devices: (.*?)\W"
MUTED_REGEX_PATTERN = r"Muted: (.*?)\W"
VOLUME_REGEX_PATTERN = r"\): (\d{1,})"

PROP_REGEX_PATTERN = r".*?\[(.*?)]"
WIFIMAC_PROP_REGEX_PATTERN = "wifimac" + PROP_REGEX_PATTERN
WIFIMAC_REGEX_PATTERN = "ether (.*?) brd"
SERIALNO_REGEX_PATTERN = "serialno" + PROP_REGEX_PATTERN
MANUF_REGEX_PATTERN = "manufacturer" + PROP_REGEX_PATTERN
MODEL_REGEX_PATTERN = "product.model" + PROP_REGEX_PATTERN
VERSION_REGEX_PATTERN = "version.release" + PROP_REGEX_PATTERN

# ADB shell commands for getting the `screen_on`, `awake`, `wake_lock`, `audio_state`, and `current_app` properties
CMD_AUDIO_STATE = r"dumpsys audio | grep -q paused && echo -e '1\c' || (dumpsys audio | grep -q started && echo '2\c' || echo '0\c')"


class AndroidTV(BaseTV):
    """Represents an Android TV device."""

    def __init__(self, host='', adbkey='', adb_server_ip='', adb_server_port=5037, basetv=None):
        """Initialize AndroidTV object.

        :param host: Host in format <address>:port.
        :param adbkey: The path to the "adbkey" file
        :param adb_server_ip: the IP address for the ADB server
        :param adb_server_port: the port for the ADB server
        """
        if basetv:
            self.host = basetv.host
            self.adbkey = basetv.adbkey
            self.adb_server_ip = basetv.adb_server_ip
            self.adb_server_port = basetv.adb_server_port

            # keep track of whether the ADB connection is intact
            self._available = basetv._available

            # use a lock to make sure that ADB commands don't overlap
            self._adb_lock = basetv._adb_lock

            # the attributes used for sending ADB commands; filled in in `self.connect()`
            self._adb = basetv._adb  # python-adb
            self._adb_client = basetv._adb_client  # pure-python-adb
            self._adb_device = basetv._adb_device  # pure-python-adb

            # the methods used for sending ADB commands
            self.adb_shell = basetv.adb_shell
            if not self.adb_server_ip:
                # python-adb
                self.adb_shell = BaseTV._adb_shell_python_adb
            else:
                # pure-python-adb
                self.adb_shell = BaseTV._adb_shell_pure_python_adb

        else:
            BaseTV.__init__(self, host, adbkey, adb_server_ip, adb_server_port)

        # get device properties
        if self._available:
            self.device_properties = self.get_device_properties()
        else:
            self.device_properties = {}

    # ======================================================================= #
    #                                                                         #
    #                               ADB methods                               #
    #                                                                         #
    # ======================================================================= #
    def start_intent(self, uri):
        """Start an intent on the device."""
        self.adb_shell("am start -a android.intent.action.VIEW -d {}".format(uri))

    # ======================================================================= #
    #                                                                         #
    #                          Home Assistant Update                          #
    #                                                                         #
    # ======================================================================= #
    def update(self):
        """Update the device status."""
        # Get the properties needed for the update.
        screen_on, awake, wake_lock_size, _current_app, audio_state, device, muted, volume = self.get_properties(lazy=True)

        # Get the current app.
        if isinstance(_current_app, dict) and 'package' in _current_app:
            current_app = _current_app['package']
        else:
            current_app = None

        # Check if device is off.
        if not screen_on:
            return constants.STATE_OFF, current_app, device, muted, volume

        # TODO: determine the state differently based on the current app
        if audio_state:
            state = audio_state

        else:
            if not awake:
                state = constants.STATE_IDLE
            elif wake_lock_size == 1:
                state = constants.STATE_PLAYING
            else:
                state = constants.STATE_PAUSED

        return state, current_app, device, muted, volume

    # ======================================================================= #
    #                                                                         #
    #                        Home Assistant device info                       #
    #                                                                         #
    # ======================================================================= #
    def get_device_properties(self):
        """Return a dictionary of device properties."""
        properties = self.adb_shell('getprop')

        if 'wifimac' in properties:
            wifimac = re.findall(WIFIMAC_PROP_REGEX_PATTERN, properties)[0]
        else:
            wifi_out = self.adb_shell('ip addr show wlan0')
            wifimac = re.findall(WIFIMAC_REGEX_PATTERN, wifi_out)[0]

        serialno = re.findall(SERIALNO_REGEX_PATTERN, properties)[0]
        manufacturer = re.findall(MANUF_REGEX_PATTERN, properties)[0]
        model = re.findall(MODEL_REGEX_PATTERN, properties)[0]
        version = re.findall(VERSION_REGEX_PATTERN, properties)[0]

        props = {'wifimac': wifimac,
                 'serialno': serialno,
                 'manufacturer': manufacturer,
                 'model': model,
                 'sw_version': version}

        return props

    # ======================================================================= #
    #                                                                         #
    #                               properties                                #
    #                                                                         #
    # ======================================================================= #
    @property
    def audio_state(self):
        """Check if audio is playing, paused, or idle."""
        output = self.adb_shell(CMD_AUDIO_STATE)
        if output is None:
            return None
        if output == '1':
            return constants.STATE_PAUSED
        if output == '2':
            return constants.STATE_PLAYING
        return constants.STATE_IDLE

    @property
    def device(self):
        """Get the current playback device."""
        output = self.adb_shell("dumpsys audio")
        if not output:
            return None

        stream_block = re.findall(BLOCK_REGEX_PATTERN, output, re.DOTALL | re.MULTILINE)[0]
        return re.findall(DEVICE_REGEX_PATTERN, stream_block, re.DOTALL | re.MULTILINE)[0]

    @property
    def muted(self):
        """Whether or not the volume is muted."""
        output = self.adb_shell("dumpsys audio")
        if not output:
            return None

        stream_block = re.findall(BLOCK_REGEX_PATTERN, output, re.DOTALL | re.MULTILINE)[0]
        return re.findall(MUTED_REGEX_PATTERN, stream_block, re.DOTALL | re.MULTILINE)[0] == 'true'

    @property
    def volume(self):
        """Get the volume level."""
        output = self.adb_shell("dumpsys audio")
        if not output:
            return None

        stream_block = re.findall(BLOCK_REGEX_PATTERN, output, re.DOTALL | re.MULTILINE)[0]
        device = re.findall(DEVICE_REGEX_PATTERN, stream_block, re.DOTALL | re.MULTILINE)[0]
        volume_level = re.findall(device + VOLUME_REGEX_PATTERN, stream_block, re.DOTALL | re.MULTILINE)[0]

        return round(1 / 15 * float(volume_level), 2)

    def get_properties(self, lazy=False):
        """Get the properties needed for Home Assistant updates."""
        output = self.adb_shell(constants.CMD_SCREEN_ON + (constants.CMD_SUCCESS1 if lazy else constants.CMD_SUCCESS1_FAILURE0) + " && " +
                                constants.CMD_AWAKE + (constants.CMD_SUCCESS1 if lazy else constants.CMD_SUCCESS1_FAILURE0) + " && " +
                                constants.CMD_WAKE_LOCK_SIZE + " && " +
                                constants.CMD_CURRENT_APP + " && " +
                                "dumpsys audio")

        # ADB command was unsuccessful
        if output is None:
            return None, None, None, None, None, None, None, None

        # `screen_on` property
        if not output:
            return False, False, -1, None, None, None, None, None
        screen_on = output[0] == '1'

        # `awake` property
        if len(output) < 2:
            return screen_on, False, -1, None, None, None, None, None
        awake = output[1] == '1'

        lines = output.strip().splitlines()

        # `wake_lock_size` property
        if len(lines[0]) < 3:
            return screen_on, awake, -1, None, None, None, None, None
        wake_lock_size = int(lines[0].split("=")[1].strip())

        # `current_app` property
        if len(lines) < 2:
            return screen_on, awake, wake_lock_size, None, None, None, None, None

        matches = constants.REGEX_WINDOW.search(lines[1])
        if matches:
            # case 1: current app was successfully found
            (pkg, activity) = matches.group("package", "activity")
            current_app = {"package": pkg, "activity": activity}
        else:
            # case 2: current app could not be found
            logging.warning("Couldn't get current app, reply was %s", lines[1])
            current_app = None

        # "dumpsys audio" output
        if len(lines) < 3:
            return screen_on, awake, wake_lock_size, current_app, None, None, None, None

        audio_output = "\n".join(lines[2:])

        # `audio_state` property
        if 'started' in audio_output:
            audio_state = constants.STATE_PLAYING
        elif 'paused' in audio_output:
            audio_state = constants.STATE_PAUSED
        else:
            audio_state = constants.STATE_IDLE

        matches = re.findall(BLOCK_REGEX_PATTERN, audio_output, re.DOTALL | re.MULTILINE)
        if not matches:
            return screen_on, awake, wake_lock_size, current_app, audio_state, None, None, None
        stream_block = matches[0]

        # `device` property
        matches = re.findall(DEVICE_REGEX_PATTERN, stream_block, re.DOTALL | re.MULTILINE)
        if matches:
            device = matches[0]

            # `volume` property
            matches = re.findall(device + VOLUME_REGEX_PATTERN, stream_block, re.DOTALL | re.MULTILINE)
            if matches:
                volume = round(1 / 15 * float(matches[0]), 2)
            else:
                volume = None

        else:
            device = None
            volume = None

        # `muted` property
        matches = re.findall(MUTED_REGEX_PATTERN, stream_block, re.DOTALL | re.MULTILINE)
        if matches:
            muted = matches[0] == 'true'
        else:
            muted = None

        return screen_on, awake, wake_lock_size, current_app, audio_state, device, muted, volume

    # ======================================================================= #
    #                                                                         #
    #                           turn on/off methods                           #
    #                                                                         #
    # ======================================================================= #
    def turn_on(self):
        """Send power action if device is off."""
        self.adb_shell(constants.CMD_SCREEN_ON + " || input keyevent {0}".format(constants.KEY_POWER))

    def turn_off(self):
        """Send power action if device is not off."""
        self.adb_shell(constants.CMD_SCREEN_ON + " && input keyevent {0}".format(constants.KEY_POWER))
