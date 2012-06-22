#!/usr/bin/env python
# author:  Hua Liang [ Stupid ET ]
# email:   et@everet.org
# website: http://EverET.org
#

import socket

host = ''
port = 12345

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((host, port))
s.listen(5)

while True:
    clientfd, clientaddr = s.accept()
    clientfd.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n<h1>Hello, ET</h1>')
    clientfd.close()

