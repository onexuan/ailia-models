import sys
import time
import argparse

import numpy as np
import cv2

import ailia

# import original modules
sys.path.append('../util')
from utils import check_file_existance  # noqa: E402
from model_utils import check_and_download_models  # noqa: E402
from image_utils import load_image  # noqa: E402
import webcamera_utils  # noqa: E402C
from adain_utils import *  # noqa: E402C


# ======================
# Parameters
# ======================
VGG_WEIGHT_PATH = 'adain-vgg.onnx'
VGG_MODEL_PATH = 'adain-vgg.onnx.prototxt'
DEC_WEIGHT_PATH = 'adain-decoder.onnx'
DEC_MODEL_PATH = 'adain-decoder.onnx.prototxt'
REMOTE_PATH = 'https://storage.googleapis.com/ailia-models/adain/'

IMAGE_PATH = 'cornell.jpg'
STYLE_PATH = 'woman_with_hat_matisse.jpg'
SAVE_IMAGE_PATH = 'output.png'
IMAGE_HEIGHT = 512
IMAGE_WIDTH = 512


# ======================
# Arguemnt Parser Config
# ======================
parser = argparse.ArgumentParser(
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    description='Arbitrary Style Transfer Model',    
)
parser.add_argument(
    '-i', '--input', metavar='IMAGE',
    default=IMAGE_PATH,
    help='The input image path.'
)
parser.add_argument(
    '-t', '--style', metavar='STYLE_IMAGE',
    default=STYLE_PATH,
    help='The style image path.'
)
parser.add_argument(
    '-v', '--video', metavar='VIDEO',
    default=None,
    help='You can convert the input video by entering style image.' +
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
# Utils
# ======================
# TODO multiple style image and weight feature
def style_transfer(vgg, decoder, content, style, alpha=1.0):
    assert (0.0 <= alpha <= 1.0)
    content_f = vgg.predict(content.astype(np.float32))
    style_f = vgg.predict(style)
    feat = adaptive_instance_normalization(content_f, style_f)
    feat = feat * alpha + content_f * (1 - alpha)
    return decoder.predict(feat)


# ======================
# Main functions
# ======================
def image_style_transfer():
    # prepare input data
    input_img = load_image(
        args.input,
        (IMAGE_HEIGHT, IMAGE_WIDTH),
        normalize_type='255',
        gen_input_ailia=True
    )
    
    src_h, src_w, _ = cv2.imread(args.input).shape
    style_img = load_image(
        args.style,
        (IMAGE_HEIGHT, IMAGE_WIDTH),
        normalize_type='255',
        gen_input_ailia=True
    )

    # net initialize
    env_id = ailia.get_gpu_environment_id()
    print(f'env_id: {env_id}')
    vgg = ailia.Net(VGG_MODEL_PATH, VGG_WEIGHT_PATH, env_id=env_id)
    decoder = ailia.Net(DEC_MODEL_PATH, DEC_WEIGHT_PATH, env_id=env_id)

    # inference
    print('Start inference...')
    if args.benchmark:
        print('BENCHMARK mode')
        for i in range(5):
            start = int(round(time.time() * 1000))
            preds_ailia = style_transfer(vgg, decoder, input_img, style_img)
            end = int(round(time.time() * 1000))
            print(f'\tailia processing time {end - start} ms')
    else:
        preds_ailia = style_transfer(vgg, decoder, input_img, style_img)
        
    res_img = cv2.cvtColor(
        preds_ailia[0].transpose(1, 2, 0),
        cv2.COLOR_RGB2BGR
    )
    res_img = cv2.resize(res_img, (src_w, src_h))
    cv2.imwrite(args.savepath, np.clip(res_img * 255 + 0.5, 0, 255))
    print('Script finished successfully.')


def video_style_transfer():
    # net initialize
    env_id = ailia.get_gpu_environment_id()
    print(f'env_id: {env_id}')
    vgg = ailia.Net(VGG_MODEL_PATH, VGG_WEIGHT_PATH, env_id=env_id)
    decoder = ailia.Net(DEC_MODEL_PATH, DEC_WEIGHT_PATH, env_id=env_id)

    if args.video == '0':
        print('[INFO] Webcam mode is activated')
        capture = cv2.VideoCapture(0)
        if not capture.isOpened():
            print("[ERROR] webcamera not found")
            sys.exit(1)
    else:
        if check_file_existance(args.video):
            capture = cv2.VideoCapture(args.video)

    # Style image
    style_img = load_image(
        args.style,
        (IMAGE_HEIGHT, IMAGE_WIDTH),
        normalize_type='255',
        gen_input_ailia=True
    )

    # create video writer if savepath is specified as video format
    if args.savepath != SAVE_IMAGE_PATH:
        writer = webcamera_utils.get_writer(
            args.savepath, IMAGE_HEIGHT, IMAGE_WIDTH
        )
    else:
        writer = None

    while(True):
        ret, frame = capture.read()
        if (cv2.waitKey(1) & 0xFF == ord('q')) or not ret:
            break

        # Resize by padding the perimeter.
        _, input_data = webcamera_utils.preprocess_frame(
            frame, IMAGE_HEIGHT, IMAGE_WIDTH, normalize_type='255'
        )
        
        # # The image will be distorted by normal resize
        # input_data = (cv2.cvtColor(
        #     cv2.resize(frame, (IMAGE_WIDTH, IMAGE_HEIGHT)), cv2.COLOR_BGR2RGB
        # ) / 255.0).transpose(2, 0, 1)[np.newaxis, :, :, :]

        # inference
        preds_ailia = style_transfer(vgg, decoder, input_data, style_img)
        
        # postprocessing
        res_img = cv2.cvtColor(
            preds_ailia[0].transpose(1, 2, 0), cv2.COLOR_RGB2BGR
        )

        cv2.imshow('frame', res_img)

        # save results
        if writer is not None:
            writer.write(np.clip(res_img * 255 + 0.5, 0, 255).astype(np.uint8))

    capture.release()
    cv2.destroyAllWindows()

    print('Script finished successfully.')


def main():
    # model files check and download
    check_and_download_models(VGG_WEIGHT_PATH, VGG_MODEL_PATH, REMOTE_PATH)
    check_and_download_models(DEC_WEIGHT_PATH, DEC_MODEL_PATH, REMOTE_PATH)

    if args.video is not None:
        # video mode
        video_style_transfer()
    else:
        # image mode
        image_style_transfer()


if __name__ == '__main__':
    main()
