from flask import Response, stream_with_context, Flask, render_template, request, url_for, redirect
import cv2
from utils import postprocess
import serial
from time import sleep
from datetime import datetime
import requests
import googletrans
import sqlite3  # salite3
import threading

app = Flask(__name__)
conn = sqlite3.connect("database.db")  # splite3 db 연결
# print("Opened database successfully")
# conn.execute("CREATE TABLE IF NOT EXISTS Board(name TEXT, context TEXT)")  # Board 라는 DB생성
# print("TABLE Created Successfully")
conn.commit()  # 지금껏 작성한 SQL, DB에 반영 commit
conn.close()  # 작성 다한 DB는 닫아줘야함 close


camera = cv2.VideoCapture(0)
rfid = str()
TARGET_URL = 'https://notify-api.line.me/api/notify'
translator = googletrans.Translator()
ser = serial.Serial('COM3', 9600, timeout=1)

def generate_rt_frame():
    confThreshold = 0.85  # Confidence threshold
    nmsThreshold = 0.7  # Non-maximum suppression threshold
    inpWidth = 416  # Width of network's input image
    inpHeight = 416  # Height of network's input image

    # Load names of classes
    classesFile = "obj.names"

    with open(classesFile, 'rt') as f:
        classes = f.read().rstrip('\n').split('\n')

    # Give the configuration and weight files for the model and load the network using them.
    modelConfiguration = "yolov3-obj.cfg"
    modelWeights = "yolov3-obj_2400.weights"

    net = cv2.dnn.readNetFromDarknet(modelConfiguration, modelWeights)
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    layersNames = net.getLayerNames()
    # Get the names of the output layers, i.e. the layers with unconnected outputs
    output_layer = [layersNames[i[0] - 1] for i in net.getUnconnectedOutLayers()]

    while True:
        global rfid
        line = None
        success, frame = camera.read()
        if not success:
            break
        else:
            # Create a 4D blob from a frame.
            blob = cv2.dnn.blobFromImage(frame, 1 / 255, (inpWidth, inpHeight), [0, 0, 0], 1, crop=True)

            # Sets the input to the network
            net.setInput(blob)

            # Runs the forward pass to get output of the output layers
            outs = net.forward(output_layer)

            # Remove the bounding boxes with low confidence
            helmet = postprocess(frame, outs, confThreshold, nmsThreshold, classes)
            try:
                line = ser.readline().decode("utf-8")
                if (helmet == 0) and (line != None):
                    rfid = line
            except ValueError:
                pass
            t, _ = net.getPerfProfile()

            label = 'Inference time: %.2f ms' % (t * 1000.0 / cv2.getTickFrequency())

            cv2.putText(frame, label, (0, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255))

            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


def generate_img_frame():
    while True:
        number = 0
        camera2 = cv2.VideoCapture("ex2.mp4")
        while True:
            number += 1
            success2, frame2 = camera2.read()
            if not success2:
                break
            else:
                if number == 50:
                    try:
                        message_cn = translator.translate('3번 방에서 불이 났습니다.', dest='zh-cn')
                        message_vi = translator.translate('3번 방에서 불이 났습니다.', dest='vi')
                        requests.post(TARGET_URL, headers={'Authorization': 'Bearer ' + 'k9EwLp0AQuS3MGNfCTPeI3HhJS3uweE2fnnVwu2r1CY'}, data={'message': message_cn.text})
                        #requests.post(TARGET_URL, headers={'Authorization': 'Bearer ' + 'lg1w8gMgU02I7zNnBTn9ttdxo4gChVhv6QoTv6z4R1T'}, data={'message': message_vi.text})
                    except Exception as ex:
                        pass
                ret2, buffer2 = cv2.imencode('.jpg', frame2)
                frame2 = buffer2.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame2 + b'\r\n')


def stream_template(template_name, **context):
    app.update_template_context(context)
    t = app.jinja_env.get_template(template_name)
    rv = t.stream(context)
    rv.disable_buffering()
    return rv


def generate():
    global rfid
    while True:
        if rfid != "":
            yield str(datetime.now().strftime("%c")) + " " + rfid + "헬멧 미착용"
            try:
                message_cn = translator.translate("헬멧 미착용", dest='zh-cn')
                message_vi = translator.translate("헬멧 미착용", dest='vi')
                requests.post(TARGET_URL, headers={'Authorization': 'Bearer ' + 'k9EwLp0AQuS3MGNfCTPeI3HhJS3uweE2fnnVwu2r1CY'}, data={'message': rfid + message_cn.text})
                # requests.post(TARGET_URL, headers={'Authorization': 'Bearer ' + 'lg1w8gMgU02I7zNnBTn9ttdxo4gChVhv6QoTv6z4R1T'}, data={'message': rfid + message_vi.text})
            except Exception as ex:
                print(ex)
            rfid = ""
            sleep(1)


@app.route('/')
def login():
    return render_template('login.html')

@app.route('/menu')
def stream_view():
    rows = generate()
    return Response(stream_with_context(stream_template('menu.html', rows=rows)))


@app.route('/rt-video')
def rt_video():
    return Response(generate_rt_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/img-video')
def img_video():
    return Response(generate_img_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/cctv')
def cctv():
    return render_template('cctv.html')


@app.route('/notice')
def notice():
    con = sqlite3.connect("database.db")
    cur = con.cursor()
    cur.execute("SELECT * FROM Board")
    rows = cur.fetchall()
    return render_template("notice.html", rows=rows)


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        try:
            name = request.form["name"]
            context = request.form["context"]
            # DB에 접근해서, 데이터를 삽입할때는, 직접 DB를 열어야되는데, 윗 과정처럼, close까지 하기 힘드니깐, 하는 방식, 결과는 같은 것 !
            with sqlite3.connect("database.db") as con:
                cur = con.cursor()
                cur.execute(f"INSERT INTO Board(name,context) VALUES('{name}','{context}')")
                message_cn = translator.translate(f"{name}: {context}", dest='zh-cn')
                message_vi = translator.translate(f"{name}: {context}", dest='vi')
                requests.post(TARGET_URL, headers={'Authorization': 'Bearer ' + 'k9EwLp0AQuS3MGNfCTPeI3HhJS3uweE2fnnVwu2r1CY'}, data={'message': message_cn.text})
                # requests.post(TARGET_URL, headers={'Authorization': 'Bearer ' + 'lg1w8gMgU02I7zNnBTn9ttdxo4gChVhv6QoTv6z4R1T'}, data={'message': message_vi.text})
                con.commit()
        except:
            con.rollback()  # DB 롤백함수, SQL이 오류나면, 반영전, 이전 상태로 돌리는 것
        finally:
            return redirect(url_for("notice"))
    else:
        return render_template("add.html")


@app.route("/delete/<uid>")
def delete(uid):
    # 들어온 uid 값이랑 name이랑 delete 연산하고 반영
    with sqlite3.connect("database.db") as con:
        cur = con.cursor()
        cur.execute(f"DELETE FROM Board WHERE context='{uid}'")
        con.commit()

    return redirect(url_for('notice'))  # 삭제 반영하고, 반영됬는지, board함수 리다이렉트, / 페이지 렌더링

if __name__ == "__main__":
    app.run(debug=False)