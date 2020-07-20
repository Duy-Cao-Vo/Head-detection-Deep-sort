from imutils.video import VideoStream
import imagezmq
import socket
import imutils

# path = "rtsp://172.16.689.203:8080/h264_ulaw.sdp"
path = "rtsp://admin:ICUIFC@172.16.68.146:554/Streaming/Channels/101/"

cap = VideoStream(path)

sender = imagezmq.ImageSender(connect_to='tcp://localhost:5555')
cam_id = socket.gethostname()

stream = cap.start()

while True:
    frame = stream.read()
    if frame is None:
        break
    frame = imutils.resize(frame, width=720)
    sender.send_image(cam_id, frame)