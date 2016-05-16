# -*- coding: utf-8 -*-

import os
import json
import zlib

from _quickavro import Encoder

from .constants import *
from .errors import *
from .utils import *


def read_header(data):
    with BinaryEncoder(HEADER_SCHEMA) as encoder:
        header, offset = encoder.read_record(data)
        if not header:
            raise InvalidSchemaError("Unable to read Avro header.")
        return header, offset

def write_header(schema, sync_marker, codec="null"):
    with BinaryEncoder(HEADER_SCHEMA, codec) as encoder:
        header = {
            "magic": MAGIC,
            "meta": {
                "avro.codec": codec,
                "avro.schema": json.dumps(schema)
            },
            "sync": sync_marker
        }
        return encoder.write(header)


class BinaryEncoder(Encoder):
    def __init__(self, schema=None, codec="null"):
        super(BinaryEncoder, self).__init__()
        self._codec = None
        self._schema = None
        self.sync_marker = os.urandom(SYNC_SIZE)
        self.codec = codec
        if schema:
            self.schema = schema
        self.block = []
        self.block_count = 0
        self.block_size = 0

    def close(self):
        pass

    @property
    def codec(self):
        return self._codec

    @codec.setter
    def codec(self, codec):
        if codec not in {"deflate", "null", "snappy"}:
            raise CodecNotSupported("Codec {0} is not supported.".format(codec))
        self._codec = codec

    @property
    def header(self):
        return write_header(self.schema, self.sync_marker, self.codec)

    def read_block(self, block):
        block_count, offset = self.read_long(block[:MAX_VARINT_SIZE])
        if block_count < 0:
            return None, None
        block = block[offset:]
        block_length, offset = self.read_long(block[:MAX_VARINT_SIZE])
        block, data = block[offset:block_length+offset], block[block_length+offset:]
        return block, data

    def read_blocks(self, data):
        if not self.schema:
            raise SchemaNotFound("Schema must be provided before attempting to read Avro data.")
        while True:
            block, data = self.read_block(data)
            if not block:
                break
            self.block_count += 1
            sync_marker, data = data[:SYNC_SIZE], data[SYNC_SIZE:]
            for record in self.read(block):
                yield record

    def read_header(self, data):
        data = memoryview(data)
        header, offset = read_header(data)
        data = data[offset:]
        return header, data

    @property
    def schema(self):
        if not self._schema:
            raise SchemaNotFound("Schema must be provided before attempting to read Avro data.")
        return self._schema

    @schema.setter
    def schema(self, schema):
        self._schema = schema
        self.set_schema(json.dumps(schema))

    def write_block(self):
        data = "".join(self.block)
        block_count = self.write_long(len(self.block))
        if self.codec == 'deflate':
            data = zlib.compress(data)[2:-1]
        elif self.codec == 'snappy':
            crc = crc32(data)
            data = snappy_compress(data)
            data = data + crc
        block_length = self.write_long(len(data))
        self.block = []
        self.block_count += 1
        self.block_size = 0
        return block_count + block_length + data + self.sync_marker

    def write_blocks(self, records):
        for record in records:
            if self.block_size >= DEFAULT_SYNC_INTERVAL:
                yield self.write_block()
            self.write_record(record)
        if self.block:
            yield self.write_block()

    def write_record(self, record):
        record = self.write(record)
        self.block_size += len(record)
        self.block.append(record)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()


class enum(object):
    def __init__(self, name, value, index):
        self.name = name
        self.value = value
        self.index = index

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.__str__()


class Enum(object):
    def __init__(self, name, values):
        self.name = name
        self.symbols = values.split(" ")
        for i, v in enumerate(self.symbols):
            setattr(self, v, enum(self.name, v, i))

    @property
    def T(self):
        return {"name": self.name, "type": "enum", "symbols": self.symbols}
