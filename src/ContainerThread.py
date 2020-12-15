import socket
import threading
import docker
import time
import iptc
from enum import Enum

from hpotter.logger import logger
from hpotter.plugins.OneWayThread import OneWayThread

class ContainerThread(threading.Thread):
    def __init__(self, source, connection, config):
        super().__init__()
        self.source = source
        logger.debug(self.source)
        self.connection = connection
        self.config = config
        self.container_ip = self.container_port = self.container_protocol = None
        self.dest = self.thread1 = self.thread2 = self.container = None

    '''
    Need to make a different one for macos as docker desktop for macos
    doesn't allow connecting to a docker-defined network. I'm thinking of
    using 127.0.0.1 and mapping the internal port to one in the range
    25000-25999 as those don't appear to be claimed in
    https://support.apple.com/en-us/HT202944
    I believe client sockets start in the 40000's
    '''
    def connect_to_container(self):
        nwsettings = self.container.attrs['NetworkSettings']
        self.container_ip = nwsettings['Networks']['bridge']['IPAddress']
        logger.debug(self.container_ip)

        ports = nwsettings['Ports']
        assert len(ports) == 1

        for p in ports.keys():
            self.container_port = int(p.split('/')[0])
            self.container_protocol = p.split('/')[1]
        logger.debug(self.container_port)
        logger.debug(self.container_protocol)

        for x in range(9):
            try:
                self.dest = socket.create_connection( \
                    (self.container_ip, self.container_port), timeout=2)
                self.dest.settimeout(None)
                logger.debug(self.dest)
                return
            except Exception as err:
                logger.debug(err)
                time.sleep(2)

        logger.info('Unable to connect to ' + self.container_ip + ':' + \
            self.container_port)
        logger.info(err)
        raise err

    def create_rules(self):
        proto = self.container_protocol.lower()
        srcIP = self.source.getpeername()[0]
        dstIP = self.container_ip
        srcport = str(self.source.getpeername()[1])
        dstport = str(self.container_port)


        self.to_rule = { \
            'src': srcIP, \
            'dst': dstIP, \
            'target': 'ACCEPT', \
            'protocol': proto, \
            proto: {'sport': srcport, 'dport': dstport} \
        }
        logger.debug(self.to_rule)
        iptc.easy.add_rule('filter', 'FORWARD', self.to_rule)

        self.from_rule = { \
            'src': dstIP, \
            'dst': srcIP, \
            'target': 'ACCEPT', \
            'protocol': proto, \
            proto: {'sport': dstport, 'dport': srcport} \
        }
        logger.debug(self.from_rule)
        iptc.easy.add_rule('filter', 'FORWARD', self.from_rule)

        self.drop_rule = { \
            'src': dstIP, \
            'dst': '!' + srcIP, \
            'target': 'DROP' \
        }
        logger.debug(self.drop_rule)
        iptc.easy.add_rule('filter', 'FORWARD', self.drop_rule)

    def remove_rules(self):
        logger.debug('Removing rules')
        iptc.easy.delete_rule('filter', "FORWARD", self.to_rule)
        iptc.easy.delete_rule('filter', "FORWARD", self.from_rule)
        iptc.easy.delete_rule('filter', "FORWARD", self.drop_rule)

    def run(self):
        try:
            client = docker.from_env()
            self.container = client.containers.run(self.config['container'], detach=True)
            logger.info('Started: %s', self.container)
            self.container.reload()
        except Exception as err:
            logger.info(err)
            return

        try:
            self.connect_to_container()
        except Exception as err:
            logger.info(err)
            self.stop_and_remove()
            return

        self.create_rules()

        logger.debug('Starting thread1')
        self.thread1 = OneWayThread(self.source, self.dest, self.connection, self.config, 'request')
        self.thread1.start()

        logger.debug('Starting thread2')
        self.thread2 = OneWayThread(self.dest, self.source, self.connection, self.config, 'response')
        self.thread2.start()

        logger.debug('Joining thread1')
        self.thread1.join()
        logger.debug('Joining thread2')
        self.thread2.join()

        self.remove_rules()

        self.dest.close()
        self.stop_and_remove()

    def stop_and_remove(self):
        logger.debug(str(self.container.logs()))
        logger.info('Stopping: %s', self.container)
        self.container.stop()
        logger.info('Removing: %s', self.container)
        self.container.remove()

    def shutdown(self):
        self.thread1.shutdown()
        self.thread2.shutdown()
        self.dest.close()
        self.stop_and_remove()

