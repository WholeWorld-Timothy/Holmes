import asyncio
from ai.backend.start_server import WSServer

if __name__ == '__main__':
    server_port = 8339
    s = WSServer(server_port)
    # t = threading.Thread(target=s.serve_forever)
    # t.daemon = True
    # t.start()
    s.serve_forever()
