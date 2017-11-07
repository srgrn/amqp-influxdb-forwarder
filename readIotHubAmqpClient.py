#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import time
import datetime

import configparser
from influxdb import InfluxDBClient
from proton.handlers import MessagingHandler
from proton.reactor import Container, Selector

# Config file must be bound to docker image at runtime
CONFIG_FILE_PATH = 'config/config.properties'

FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT)
logger = logging.getLogger(__name__)


def load_config(path):
    logging.debug('Setup logging configuration')
    if os.path.exists(path):
        logging.debug('loading config file')
        try:
            config = configparser.ConfigParser()
            config.read(path)
        except IOError:
            logging.critical("Failed to load the file")
            sys.exit(1)
        except ValueError:
            logging.critical("Failed to read the config file probably not proper json")
            sys.exit(1)
        except Exception as e:
            raise e
        return config
    else:
        logging.debug('no config file specified')
        logging.debug('using environment variables')
        config = {}
        for key in os.environ.keys():
            if key.startswith('CONF_'):
                keyname = key.replace('CONF_', '')
                if '__' in keyname:
                    splitted = keyname.split('__')
                    if config.get(splitted[0]) is None:
                        config[splitted[0]] = {}
                    config[splitted[0]][splitted[1]] = os.environ[key]
                else:
                    config[keyname] = os.environ[key]
        return config


configp = load_config(CONFIG_FILE_PATH)
print(configp)
influx_config = configp['influxdb']
DB_NAME = influx_config['database']
logging.info("Using database: '{0}'".format(DB_NAME))

influxdb_client = InfluxDBClient(influx_config['host'],
                                 influx_config['port'],
                                 influx_config['user'],
                                 influx_config['pass'],
                                 DB_NAME)


def connect_influxdb():
    while True:
        try:
            dbs = influxdb_client.get_list_database()
            if DB_NAME not in dbs:
                influxdb_client.create_database(DB_NAME)
        except Exception:
            logger.exception("Error connecting to InfluxDB. Retrying in 30sec")
            time.sleep(30)
            continue
        else:
            logging.info("connected to influxdb")
            break


def connect_iothub(event):
    # -1 = beginning
    #  @latest = only new messages
    offset = "@latest"
    selector = Selector(u"amqp.annotation.x-opt-offset > '" + offset + "'")

    azure_config = configp['azure']
    amqp_url = azure_config['iothub_amqp_url']
    partition_name = azure_config['iothub_partition_name']
    while True:
        try:
            conn = event.container.connect(amqp_url, allowed_mechs="PLAIN MSCBS", session_policy=None, shared_connection=None)
            event.container.create_receiver(conn, partition_name + "/ConsumerGroups/$default/Partitions/0",
                                            options=selector)
            event.container.create_receiver(conn, partition_name + "/ConsumerGroups/$default/Partitions/1",
                                            options=selector)
            event.container.create_receiver(conn, partition_name + "/ConsumerGroups/$default/Partitions/2",
                                            options=selector)
            event.container.create_receiver(conn, partition_name + "/ConsumerGroups/$default/Partitions/3",
                                            options=selector)
        except Exception:
            logger.exception("Error connecting to IotHub. Retrying in 30sec")
            time.sleep(30)
            continue
        else:
            break


def write_influxdb(payload):
    while True:
        try:
            influxdb_client.write_points(payload)
        except Exception:
            logger.exception("Error writing to InfluxDB. Retrying in 30sec")
            time.sleep(30)
            continue
        else:
            break

def build_fields(body):
    ret = {}
    for key in body.keys():
        ret[key] = body[key]
    return ret

def convert_to_influx_format(message):
    name = message.annotations["iothub-connection-device-id"]
    try:
        body = json.loads(message.body)
    except json.decoder.JSONDecodeError:
        return
    
    time = body.get("time",message.annotations["iothub-enqueuedtime"])
    time = datetime.datetime.fromtimestamp(time/1000.0).strftime('%Y-%m-%d %H:%M:%S.%f')

    json_body = [
        {'measurement': name, 'time': time, 'fields': 
            build_fields(body)
        }
    ]

    return json_body


class Receiver(MessagingHandler):
    def __init__(self):
        super(Receiver, self).__init__()

    def on_start(self, event):
        connect_influxdb()
        connect_iothub(event)
        logging.info("Setup complete")

    def on_message(self, event_received):
        logging.info("Event received: '{0}'".format(event_received.message))

        payload = convert_to_influx_format(event_received.message)

        if payload is not None:
            logging.info("Write points: {0}".format(payload))
            write_influxdb(payload)

    def on_connection_closing(self, event):
        logging.error("Connection closing - trying to reestablish connection")
        connect_iothub(event)

    def on_connection_closed(self, event):
        logging.error("Connection closed")
        connect_iothub(event)

    def on_connection_error(self, event):
        logging.error("Connection error")

    def on_disconnected(self, event):
        logging.error("Disconnected")

    def on_session_closing(self, event):
        logging.error("Session closing")

    def on_session_closed(self, event):
        logging.error("Session closed")

    def on_session_error(self, event):
        logging.error("Session error")


def main():
    try:
        Container(Receiver()).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
