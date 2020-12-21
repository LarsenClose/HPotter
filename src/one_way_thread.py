import threading

from src import tables
from src.logger import logger
from src.lazy_init import lazy_init

class one_way_thread(threading.Thread):
    # pylint: disable=E1101, W0613
    @lazy_init
    def __init__(self, source, dest, connection, config, direction, database):
        super().__init__()

        self.length = self.config.get(self.direction + '_length', 4096)
        self.commands = self.config.get(self.direction + '_commands', 10)
        self.delimiters = self.config.get(self.direction + '_delimiters',
            ['\n', '\r'])

        self.shutdown_requested = False

    def _read(self):
        logger.debug('%s reading from: %s', self.direction, str(self.source))
        data = self.source.recv(4096)
        logger.debug('%s read: %s', self.direction, str(data))

        return data

    def _write(self, data):
        logger.debug('%s sending to: %s', self.direction, str(self.dest))
        self.dest.sendall(data)
        logger.debug('%s sent: %s', self.direction, str(data))

    def _too_many_commands(self, data):
        if self.commands > 0:
            sdata = str(data)
            count = 0
            for delimiter in self.delimiters:
                count = max(count, sdata.count(delimiter))
            if count >= self.commands:
                logger.info('Commands exceeded, stopping')
                return True

        return False

    def run(self):
        total = b''
        while True:
            try:
                data = self._read()
                if not data or data == b'':
                    break
                self._write(data)
            except Exception as exception:
                logger.debug('%s %s', self.direction, str(exception))
                break

            total += data

            if self.shutdown_requested:
                break

            if self.length > 0 and len(total) >= self.length:
                logger.debug('Length exceeded')
                break

            if self._too_many_commands(data):
                break

        logger.debug(self.length)
        logger.debug(len(total))
        logger.debug(self.direction)
        if self.length > 0 and len(total) > 0:
            self.database.write(tables.Data(direction=self.direction,
                data=str(total), connection=self.connection))
        self.source.close()
        self.dest.close()

    def shutdown(self):
        self.shutdown_requested = True
