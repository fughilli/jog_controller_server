import asyncio
import socket
import base64
from stream_utils.control_message_pb2 import Control


def GetDefaultIp():
    test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    test_socket.connect(('8.8.8.8', 80))
    ip_addr = test_socket.getsockname()[0]
    test_socket.close()
    return ip_addr


class ProtoDecoder(object):
    def __init__(self, proto_handler=None, proto_type=None):
        self.proto_handler = proto_handler
        self.proto_type = proto_type

    def ProcessFrame(self, frame):
        wire_bytes = base64.b64decode(frame)
        proto = self.proto_type()
        proto.ParseFromString(wire_bytes)
        self.proto_handler(proto)


class FrameExtractor(object):
    def __init__(self, frame_handler=None, prefix=b'^', suffix=b'$'):
        self.frame_handler = frame_handler
        self.prefix = prefix
        self.suffix = suffix
        self.buffer = b''

    def ProcessData(self, data):
        self.buffer += data

        while True:
            suffix_index = self.buffer.find(self.suffix)
            if suffix_index == -1:
                return

            all_before_suffix = self.buffer[:suffix_index]
            self.buffer = self.buffer[suffix_index + len(self.suffix):]

            prefix_index = all_before_suffix.rfind(self.prefix)

            if prefix_index == -1:
                # Prefix was not found before the suffix in the buffer. Nothing
                # more to do.
                return

            frame = all_before_suffix[prefix_index + len(self.prefix):]
            self.frame_handler(frame)

    def GetResponse(self):
        return None


def HandleProto(proto):
    print(proto)


proto_decoder = ProtoDecoder(proto_handler=HandleProto, proto_type=Control)
processor = FrameExtractor(frame_handler=proto_decoder.ProcessFrame)


async def handle_client(client):
    request = None
    try:
        while True:
            request = await loop.sock_recv(client, 255)
            processor.ProcessData(request)
            response = processor.GetResponse()
            if response is not None:
                await loop.sock_sendall(client, response)
    finally:
        client.close()


async def run_server():
    while True:
        client, _ = await loop.sock_accept(server)
        loop.create_task(handle_client(client))


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((GetDefaultIp(), 5533))
server.listen(8)
server.setblocking(False)

loop = asyncio.get_event_loop()
loop.run_until_complete(run_server())
