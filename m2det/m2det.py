import time
import math
import sys
import argparse
import pathlib

import numpy as np
import cv2

import ailia

# import original modules
sys.path.append('../util')
from model_utils import check_and_download_models 
from webcamera_utils import adjust_frame_size  
from detector_utils import plot_results, load_image 

# ======================
# Parameters
# ======================

WEIGHT_PATH = './m2det.onnx'
MODEL_PATH = './m2det.onnx.prototxt'
REMOTE_PATH = 'https://storage.googleapis.com/ailia-models/m2det/'

IMAGE_PATH = 'couple.jpg'
SAVE_IMAGE_PATH = 'output.png'
IMAGE_HEIGHT = 448  # for video mode
IMAGE_WIDTH = 448  # for video mode

COCO_CATEGORY = ['__background__'] + [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush"
]
THRESHOLD = 0.4
IOU = 0.45
KEEP_PER_CLASS = 10

# ======================
# Arguemnt Parser Config
# ======================
parser = argparse.ArgumentParser(
    description='m2det model'
)
parser.add_argument(
    '-i', '--input', metavar='IMAGE',
    default=IMAGE_PATH,
    help='The input image path.'
)
parser.add_argument(
    '-v', '--video', metavar='VIDEO',
    default=None,
    help='The input video path. ' +
         'If the VIDEO argument is set to 0, the webcam input will be used.'
)
parser.add_argument(
    '-s', '--savepath', metavar='SAVE_IMAGE_PATH',
    default=SAVE_IMAGE_PATH,
    help='Save path for the output image.'
)
parser.add_argument(
    '-b', '--benchmark',
    action='store_true',
    help='Running the inference on the same input 5 times ' +
         'to measure execution performance. (Cannot be used in video mode)'
)
args = parser.parse_args()

# ======================
# Secondaty Functions
# ======================

def nms(dets, thresh):
    """Pure Python NMS baseline."""
    x1 = dets[:, 0]
    y1 = dets[:, 1]
    x2 = dets[:, 2]
    y2 = dets[:, 3]
    scores = dets[:, 4]

    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(ovr <= thresh)[0]
        order = order[inds + 1]
    return keep

def preprocess(img, resize=512, rgb_means=(104,117,123), swap=(2, 0, 1)):
    interp_method = cv2.INTER_LINEAR
    img = cv2.resize(np.array(img), 
                     (resize, resize),
                     interpolation = interp_method).astype(np.float32)
    img -= rgb_means
    # make channel first
    img = img.transpose(swap)
    return img[None, ...]

def to_color(indx, base):
    """ return (b, r, g) tuple"""
    base2 = base * base
    b = 2 - indx / base2
    r = 2 - (indx % base2) / base
    g = 2 - (indx % base2) % base
    return b * 127, r * 127, g * 127

base = int(np.ceil(pow(len(COCO_CATEGORY), 1. / 3)))
COLORS = [to_color(x, base) for x in range(len(COCO_CATEGORY))]

def draw_detection(im, bboxes, scores, cls_inds):
    imgcv = np.copy(im)
    h, w, _ = imgcv.shape
    for i, box in enumerate(bboxes):
        cls_indx = int(cls_inds[i])
        box = [int(_) for _ in box]
        thick = int((h + w) / 300)
        cv2.rectangle(imgcv,
                      (box[0], box[1]), (box[2], box[3]),
                      COLORS[cls_indx], thick)
        mess = '%s: %.3f' % (COCO_CATEGORY[cls_indx], scores[i])
        cv2.putText(imgcv, mess, (box[0], box[1] - 7),
                    0, 1e-3 * h, COLORS[cls_indx], thick // 3)
    return imgcv

# ======================
# Main functions
# ======================
def detect_objects(img, detector):
    # get sizes for posterior rescaling
    h, w, _ = img.shape
    scale = np.asarray([w,h,w,h])
    
    # initial preprocesses
    img = preprocess(img)
    
    # feedforward
    boxes, scores = detector.predict({'input.1': img})

    boxes = boxes[0]
    scores = scores[0]
    allboxes = []
    
    # filter boxes for every class
    for j in range(1, len(COCO_CATEGORY)):
        inds = np.where(scores[:,j] > THRESHOLD)[0]
        if len(inds) == 0:
            continue
        c_bboxes = boxes[inds]
        c_scores = scores[inds, j]
        c_dets = np.hstack((c_bboxes, c_scores[:, np.newaxis])).astype(np.float32, copy=False)
        # rank ordered iou
        keep = nms(c_dets, IOU) #min_thresh, device_id=0 if cfg.test_cfg.cuda else None)
        keep = keep[:KEEP_PER_CLASS]
        c_dets = c_dets[keep, :]
        allboxes.extend([_.tolist()+[j] for _ in c_dets])
    
    
    if len(allboxes)>0:
        allboxes = np.array(allboxes)    
        # split boxes and scores
        boxes = allboxes[:,:4] * scale
        scores = allboxes[:,4]
        cls_inds = allboxes[:,5]
        return boxes, scores, cls_inds
    else:
        return [], [], []
    
def recognize_from_image(filename, detector):
    # load input image
    img = load_image(filename)
    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    
    print('Start inference...')
    if args.benchmark:
        print('BENCHMARK mode')
        for i in range(5):
            start = int(round(time.time() * 1000))
            boxes, scores, cls_inds = detect_objects(img, detector)
            end = int(round(time.time() * 1000))
            print(f'\tailia processing time {end - start} ms')
    else:
        boxes, scores, cls_inds = detect_objects(img, detector)
    
    try:
        print('\n'.join(['pos:{}, ids:{}, score:{:.3f}'.format('(%.1f,%.1f,%.1f,%.1f)' % (box[0],box[1],box[2],box[3]) \
                ,COCO_CATEGORY[int(obj_cls)], score) for box, obj_cls, score in zip(boxes,cls_inds,scores)]))
    except:
        pass
    
    # show image 
    im2show = draw_detection(img, boxes, scores, cls_inds)
    cv2.imwrite(args.savepath, im2show)
    
    print('Script finished successfully.')
    
    #cv2.imshow('demo', im2show)
    #cv2.waitKey(5000)
    #cv2.destroyAllWindows()
    
    
def recognize_from_video(video, detector):
 
    if video == '0':
        print('[INFO] Webcam mode is activated')
        capture = cv2.VideoCapture(0)
        if not capture.isOpened():
            print("[ERROR] webcamera not found")
            sys.exit(1)
    else:
        if pathlib.Path(video).exists():
            capture = cv2.VideoCapture(video)

    while(True):
        ret, img = capture.read()
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        if not ret:
            continue

        boxes, scores, cls_inds = detect_objects(img, detector)
        img = draw_detection(img, boxes, scores, cls_inds)
        cv2.imshow('frame', img)
        
        # press q to end video capture
        if cv2.waitKey(1)&0xFF == ord('q'):
            break
        if not ret:
            continue

    capture.release()
    cv2.destroyAllWindows()
    print('Script finished successfully.')
    
def main():
    # model files check and download
    check_and_download_models(WEIGHT_PATH, MODEL_PATH, REMOTE_PATH)

    # load model
    env_id = ailia.get_gpu_environment_id()
    print(f'env_id: {env_id}')
    
    detector = ailia.Net(MODEL_PATH,WEIGHT_PATH,env_id=env_id)
    
    if args.video is not None:
        # video mode
        recognize_from_video(args.video, detector)
    else:
        # image mode
        recognize_from_image(args.input, detector)


if __name__=='__main__':
    main()
