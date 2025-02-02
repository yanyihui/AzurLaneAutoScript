import os
import time
from collections import deque
from datetime import datetime
from io import BytesIO

from PIL import Image
from cached_property import cached_property

from module.base.retry import retry
from module.base.timer import Timer, timer
from module.device.ascreencap import AScreenCap
from module.exception import ScriptError
from module.logger import logger


class Screenshot(AScreenCap):
    _screenshot_method = [0, 1, 2]
    _screenshot_method_fixed = [0, 1, 2]

    _screenshot_interval_timer = Timer(0.1)
    _last_save_time = {}
    image: Image.Image

    def _screenshot_uiautomator2(self):
        image = self.device.screenshot()
        return image.convert('RGB')

    def _load_screenshot(self, screenshot, method):
        if method == 0:
            return Image.open(BytesIO(screenshot)).convert('RGB')
        elif method == 1:
            return Image.open(BytesIO(screenshot.replace(b'\r\n', b'\n'))).convert('RGB')
        elif method == 2:
            return Image.open(BytesIO(screenshot.replace(b'\r\r\n', b'\n'))).convert('RGB')
        else:
            raise ScriptError(f'Unknown method to load screenshots: {method}')

    def _process_screenshot(self, screenshot):
        for method in self._screenshot_method_fixed:
            try:
                result = self._load_screenshot(screenshot, method=method)
                self._screenshot_method_fixed = [method] + self._screenshot_method
                return result
            except OSError:
                continue

        self._screenshot_method_fixed = self._screenshot_method
        if len(screenshot) < 100:
            logger.warning(f'Unexpected screenshot: {screenshot}')
        raise OSError(f'cannot load screenshot')

    def _screenshot_adb(self):
        screenshot = self.adb_shell(['screencap', '-p'])
        return self._process_screenshot(screenshot)

    @retry(tries=10, delay=3)
    @timer
    def screenshot(self):
        """
        Returns:
            PIL.Image.Image:
        """
        self._screenshot_interval_timer.wait()
        self._screenshot_interval_timer.reset()
        method = self.config.Emulator_ControlMethod

        if method == 'aScreenCap':
            self.image = self._screenshot_ascreencap()
        elif method == 'uiautomator2':
            self.image = self._screenshot_uiautomator2()
        else:
            self.image = self._screenshot_adb()

        self.image.load()
        if self.config.Error_SaveError:
            self.screenshot_deque.append({'time': datetime.now(), 'image': self.image})

        return self.image

    @cached_property
    def screenshot_deque(self):
        return deque(maxlen=int(self.config.Error_ScreenshotLength))

    def save_screenshot(self, genre='items', interval=None, to_base_folder=False):
        """Save a screenshot. Use millisecond timestamp as file name.

        Args:
            genre (str, optional): Screenshot type.
            interval (int, float): Seconds between two save. Saves in the interval will be dropped.
            to_base_folder (bool): If save to base folder.

        Returns:
            bool: True if save succeed.
        """
        now = time.time()
        if interval is None:
            interval = self.config.SCREEN_SHOT_SAVE_INTERVAL

        if now - self._last_save_time.get(genre, 0) > interval:
            fmt = 'png'
            file = '%s.%s' % (int(now * 1000), fmt)

            folder = self.config.SCREEN_SHOT_SAVE_FOLDER_BASE if to_base_folder else self.config.SCREEN_SHOT_SAVE_FOLDER
            folder = os.path.join(folder, genre)
            if not os.path.exists(folder):
                os.mkdir(folder)

            file = os.path.join(folder, file)
            self.image.save(file)
            self._last_save_time[genre] = now
            return True
        else:
            self._last_save_time[genre] = now
            return False

    def screenshot_last_save_time_reset(self, genre):
        self._last_save_time[genre] = 0

    def screenshot_interval_set(self, interval):
        interval = max(interval, 0.1)
        if interval != self._screenshot_interval_timer.limit:
            interval = min(interval, 1.0)
            logger.info(f'Screenshot interval set to {interval}s')
            self._screenshot_interval_timer.limit = interval
