import asyncio
import socket
import base64
import socketio
import jwt
import json
import signal
from stream_utils.control_message_pb2 import Control


def SigintHandler(signal_received, frame):
    print("Ctrl-C caught, exiting...")
    server.shutdown()
    sio.disconnect()
    loop.stop()


def GenerateCncjsToken(secret):
    message = {'id': '', 'name': 'cncjs-pendant-wireless'}
    token = jwt.PyJWT().encode(message, secret, algorithm='HS256')
    return token


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

    async def ProcessFrame(self, frame):
        wire_bytes = base64.b64decode(frame)
        proto = self.proto_type()
        proto.ParseFromString(wire_bytes)
        await self.proto_handler(proto)


class FrameExtractor(object):
    def __init__(self, frame_handler=None, prefix=b'^', suffix=b'$'):
        self.frame_handler = frame_handler
        self.prefix = prefix
        self.suffix = suffix
        self.buffer = b''

    async def ProcessData(self, data):
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
            await self.frame_handler(frame)

    async def GetResponse(self):
        return None


last_wheel = 0


async def HandleProto(proto):
    global last_wheel

    if not (proto.HasField('axis') and proto.HasField('value')
            and proto.HasField('multiplier')):
        return

    axis_mapping = {
        Control.AXIS_X: "X",
        Control.AXIS_Y: "Y",
        Control.AXIS_Z: "Z"
    }
    if proto.axis not in axis_mapping.keys():
        return

    multiplier_mapping = {
        Control.MULT_X1: 1,
        Control.MULT_X10: 10,
        Control.MULT_X100: 100,
    }
    if proto.multiplier not in multiplier_mapping.keys():
        return

    axis = axis_mapping[proto.axis]
    wheel = proto.value
    multiplier = multiplier_mapping[proto.multiplier]

    if abs(wheel - last_wheel) > (10000 / multiplier):
        print("Wheel skipped, ignoring...")
        last_wheel = wheel
        return

    if wheel == last_wheel:
        return

    steps = ((wheel - last_wheel) / 4.0) / 10.0 * multiplier
    last_wheel = wheel

    command = "G91\nG0 {}{:.4f}\nG90\n".format(axis, steps)
    print("Commanding {}{:.4f}".format(axis, steps))
    await sio.emit('write', ('/dev/ttyACM0', command))


proto_decoder = ProtoDecoder(proto_handler=HandleProto, proto_type=Control)
processor = FrameExtractor(frame_handler=proto_decoder.ProcessFrame)


async def handle_client(client):
    request = None
    try:
        while True:
            request = await loop.sock_recv(client, 255)
            await processor.ProcessData(request)
            response = await processor.GetResponse()
            if response is not None:
                await loop.sock_sendall(client, response)
    finally:
        client.close()


async def run_server():
    while True:
        client, _ = await loop.sock_accept(server)
        loop.create_task(handle_client(client))


async def run_cncjs_socket():
    secret = json.load(open('jog_controller_server/secret.json'))
    token = GenerateCncjsToken(secret['secret'])
    await sio.connect('ws://routercontroller.lan:80?token=' +
                      token.decode('utf-8'))
    await sio.wait()


async def on_connect():
    print('connection established')


async def on_startup(args):
    await sio.emit('open', ('/dev/ttyACM0', {
        'baudrate': 115200,
        'controllerType': 'Grbl'
    }))


async def on_serialport_open(args):
    if not (args['port'] == '/dev/ttyACM0' and data['inuse'] == True):
        print('failed to open serial port')
        return

    print('serial port opened')


if __name__ == "__main__":
    global server
    global sio
    global loop

    signal.signal(signal.SIGINT, SigintHandler)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((GetDefaultIp(), 5533))
    server.listen(8)
    server.setblocking(False)

    sio = socketio.AsyncClient(logger=True, engineio_logger=True)

    sio.on('connect', on_connect)
    sio.on('startup', on_startup)
    sio.on('serialport:open', on_serialport_open)

    loop = asyncio.get_event_loop()
    loop.create_task(run_server())
    loop.create_task(run_cncjs_socket())
    loop.run_forever()
