import json
import os
import random
import time
import traceback
from urllib.parse import urlparse
import uuid
import boto3
import cv2
import face_recognition
import base64
import numpy as np
from requests_toolbelt.multipart import decoder
from twilio.rest import Client

dynamodb_table_name = "user"
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(dynamodb_table_name)

get_method = "GET"
post_method = "POST"

health_path = "/ping"
verify_image_path = "/verify-image"
register_path = "/register"
verify_otp_path = "/verify-otp"
resend_otp_path = "/resend-otp"

RESPONSE_MESSAGE_SUCCESS = "success"
RESPONSE_MESSAGE_NOT_FOUND = "not found"

def lambda_handler(event, context):
    http_method = event['httpMethod']
    path = event["path"]

    if http_method == get_method and path == health_path:
        response = build_response(200, message="success health check")
        
    elif http_method == post_method and path == register_path:
        content_type = event['headers'].get('Content-Type') or event['headers'].get('content-type')
        
        body = event['body']
        if event.get('isBase64Encoded', False):
            body = base64.b64decode(body)
        else:
            body = body.encode('utf-8')

        if isinstance(content_type, bytes):
            content_type = content_type.decode('utf-8')

        multipart_data = decoder.MultipartDecoder(body, content_type)

        full_name = None
        phone_number = None
        country_code = None
        face_images = []
        
        for part in multipart_data.parts:
            content_disposition = part.headers.get(b'Content-Disposition', b'').decode('utf-8')
            if 'name="full_name"' in content_disposition:
                full_name = part.text
            elif 'name="phone_number"' in content_disposition:
                phone_number = part.text
            elif 'name="country_code"' in content_disposition:
                country_code = part.text
            elif 'name="face_image"' in content_disposition:
                if len(face_images) < 3:
                    face_images.append(part.content)
        
        if len(face_images) < 3:
            return build_response(400, message="Face images must be exactly 3", status_code=400)

        if not full_name or not phone_number or not country_code or not face_images:
            return build_response(400, message= "Invalid or missing data", status_code=400)

        success, error, response_code = post_register(full_name, phone_number, country_code, face_images)

        if not success:
            return build_response(response_code, message=error, status_code=response_code)
        else:
            response = build_response(200, message="Success Register!", status_code=response_code)
        return response
    
    elif http_method == post_method and path == verify_image_path:
        content_type = event['headers'].get('Content-Type') or event['headers'].get('content-type')
        
        body = event['body']
        if event.get('isBase64Encoded', False):
            body = base64.b64decode(body)
        else:
            body = body.encode('utf-8')

        if isinstance(content_type, bytes):
            content_type = content_type.decode('utf-8')

        multipart_data = decoder.MultipartDecoder(body, content_type)

        phone_number = None
        country_code = None
        face_image = None

        for part in multipart_data.parts:
            content_disposition = part.headers[b'Content-Disposition'].decode()

            if 'name="phone_number"' in content_disposition:
                phone_number = part.text
            elif 'name="country_code"' in content_disposition:
                country_code = part.text
            elif 'name="face_image"' in content_disposition:
                face_image = part.content

        if not phone_number or not country_code or not face_image:
            response = build_response(400, message="Missing phone number, country code, or face image", status_code=400)
        else:
            data, error, response_code = post_verify_image(phone_number, country_code, face_image)

            if data and not error:
                response = build_response(response_code, message="face match found", data=data, status_code=response_code)
            elif data and error is not None:
                response = build_response(response_code, message=error, data=data, status_code=response_code)
            elif not data and error is not None and response_code != 200:
                response = build_response(response_code, message=error, data=None, status_code=response_code)
            else:
                response = build_response(400, message="Face match not found", data=None, status_code=response_code)
    elif http_method == post_method and path == verify_otp_path:
        body = json.loads(event['body'])
        phone_number = body.get('phone_number')
        country_code = body.get('country_code')
        otp = body.get('otp')

        if not phone_number or not country_code or not otp:
            response = build_response(400, message="Missing phone number, country code, or otp", data=None, status_code=400)
        else:
            data, error, response_code = post_verify_otp(phone_number, country_code, otp)

            if data and not error:
                response = build_response(response_code, message="OTP verified", data=None, status_code=response_code)
            elif data and error is not None:
                response = build_response(response_code, message=error, data=None, status_code=response_code)
            elif not data and error is not None and response_code != 200:
                response = build_response(response_code, message=error, data=None, status_code=response_code)
            else:
                response = build_response(400, message="OTP verification failed", data=None, status_code=response_code)

    elif http_method == post_method and path == resend_otp_path:
        body = json.loads(event['body'])
        phone_number = body.get('phone_number')
        country_code = body.get('country_code')

        response = {}
        if not phone_number or not country_code:
            response = build_response(400, message="Missing phone number or country code", data=None, status_code=400)
        else:
            data, error, response_code = post_resend_otp(phone_number, country_code)

            if data and not error:
                response = build_response(response_code, message="OTP sent", data=None, status_code=response_code)
            elif data and error is not None:
                response = build_response(response_code, message=error, data=None, status_code=response_code)
            elif not data and error is not None and response_code != 200:
                response = build_response(response_code, message=error, data=None, status_code=response_code)
            else:
                response = build_response(400, message="Failed to send OTP", data=None, status_code=response_code)
    else:
        response = build_response(404, message=RESPONSE_MESSAGE_NOT_FOUND, data=None, status_code=404)

    return response

def post_register(full_name, phone_number, country_code, face_images):
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('user')

        response = table.get_item(
            Key={
                'phone_number': phone_number,
                'country_code': country_code
            }
        )

        if 'Item' in response:
            return False, "Phone number and country code already registered.", 400

        for face_image in face_images:
            img_array = np.frombuffer(face_image, np.uint8)
            unknown_img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            if unknown_img is None:
                return False, "Failed to decode image. The image might be corrupt or invalid.", 500

            unknown_rgb_img = cv2.cvtColor(unknown_img, cv2.COLOR_BGR2RGB)
            face_encodings = face_recognition.face_encodings(unknown_rgb_img)

            if len(face_encodings) == 0:
                return False, 'No face detected in one of the uploaded images.', 400                

        s3_client = boto3.client('s3')
        bucket_name = 'python-face-recognition'
        s3_urls = []

        for face_image in face_images:
            file_name = f'{phone_number}-{uuid.uuid4().hex}.jpg'
            
            save_image = s3_client.put_object(
                Bucket=bucket_name,
                Key=file_name,
                Body=face_image,
                ContentType='image/jpg'
            )

            if save_image['ResponseMetadata']['HTTPStatusCode'] != 200:
                return False, "Failed to save image to S3.", 500
            
            s3_url = f'https://{bucket_name}.s3.me-central-1.amazonaws.com/{file_name}'
            s3_urls.append(s3_url)
            
        save_item = table.put_item(
            Item={
                'phone_number': phone_number,
                'country_code': country_code,
                'full_name': full_name,
                'face_images': s3_urls,
                'otp': {},  # Create an empty map for the 'otp' attribute
            }
        )

        if save_item['ResponseMetadata']['HTTPStatusCode'] != 200:
            return False, "Failed to save item to DynamoDB.", 500

        return True, None, 200
    
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        error_line = tb[-1].lineno
        error = f"Error on line {error_line}: {e}"
        return False, error, 500

def post_verify_image(phone_number, country_code, face_image):
    try:
        if not face_image or not isinstance(face_image, (bytes, bytearray)):
            return False, "Invalid image data. Ensure that the image data is properly transmitted and in bytes.", 500
        
        img_array = np.frombuffer(face_image, np.uint8)
        unknown_img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        if unknown_img is None:
            return False, "Failed to decode image. The image might be corrupt or invalid.", 500

        unknown_rgb_img = cv2.cvtColor(unknown_img, cv2.COLOR_BGR2RGB)
        unknown_img_encoding = face_recognition.face_encodings(unknown_rgb_img)

        if len(unknown_img_encoding) == 0:
            return False, "No face image found, please upload a valid face image.", 400
        
        unknown_img_encoding = unknown_img_encoding[0]
        
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('user')

        response = table.get_item(
            Key={
                'phone_number': phone_number,
                'country_code': country_code
            }
        )

        known_img_encodings = []
        if 'Item' in response:
            face_image_urls = response['Item'].get('face_images', [])
            if len(face_image_urls) < 0:
                return False, "No face image found for the registered phone number.", 400

            for face_image_url in face_image_urls:
                parsed_url = urlparse(face_image_url)
                bucket_name = parsed_url.netloc.split('.')[0]
                key = parsed_url.path.lstrip('/')
                
                s3 = boto3.client('s3')

                response = s3.get_object(Bucket=bucket_name, Key=key)
                known_img_data = response['Body'].read()
                known_img_array = np.frombuffer(known_img_data, dtype=np.uint8)
            
                known_img_bgr = cv2.imdecode(known_img_array, cv2.IMREAD_COLOR)

                known_rgb_img = cv2.cvtColor(known_img_bgr, cv2.COLOR_BGR2RGB)
                
                known_img_encodings.append(face_recognition.face_encodings(known_rgb_img)[0])

        result = face_recognition.compare_faces(known_img_encodings, unknown_img_encoding) 
        face_distances = face_recognition.face_distance(known_img_encodings, unknown_img_encoding)
        
        face_distances_list = []
        for i,face_distance in enumerate(face_distances):
            face_distances_list.append(face_distance)
            if face_distance < 0.5:
                result[i] = True
            else:
                result[i] = False

        if any(result):
            response = {
                "face_distances": face_distances_list,   
            }
            message_id, otp_code, otp_expiration, error_message = _send_otp(phone_number, country_code)

            if error_message:
                return False, error_message, 500
            
            response["message_id"] = message_id
            response["otp_code"] = otp_code
            response["otp_expiration"] = otp_expiration

            return response, None, 200

        else:
            response = {
                "face_distances": face_distances_list,   
            }
            return response, "Face match not found", 500
    
    except Exception as e: 
        tb = traceback.extract_tb(e.__traceback__)
        error_line = tb[-1].lineno
        error = f"Error on line {error_line}: {e}"
        return False, error, 500
    
def post_verify_otp(phone_number, country_code, otp_code):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('user')
    response = table.get_item(
        Key={
            'phone_number': phone_number,
            'country_code': country_code
        }
    )

    if 'Item' not in response:
        return False, "OTP verification failed. Please try again later.", 400
    
    if 'otp' not in response['Item']:
        return False, "OTP verification failed. Please try again later.", 400
    
    if int(response['Item']['otp']['code']['S']) != otp_code:
        return False, "Invalid OTP. Please try again.", 400
    
    if int(time.time()) > int(response['Item']['otp']['expiration_time']['N']):
        return False, "OTP expired. Please try again.", 400
    
    return True, None, 200

def post_resend_otp(phone_number, country_code):
    message_id, otp_code, otp_expiration, error_message = _send_otp(phone_number, country_code, resend=True)

    if error_message:
        return False, error_message, 500
    
    response = {}
    response["message_id"] = message_id
    response["otp_code"] = otp_code
    response["otp_expiration"] = otp_expiration

    return response, None, 200

def _send_otp(phone_number, country_code, resend=False):
    account_sid = os.environ['TWILIO_ACCOUNT_SID']
    auth_token = os.environ['TWILIO_AUTH_TOKEN']
    client = Client(account_sid, auth_token)

    max_retries = 5
    try:
        if resend:
            response = table.get_item(
                TableName='user',
                Key={
                    'phone_number': phone_number,
                    'country_code': country_code
                }
            )

            if 'Item' not in response:
                return None, None, None, "Failed to get OTP and expiration time from DynamoDB"
            
            if 'otp' not in response['Item']:
                return None, None, None, "Failed to get OTP and expiration time from DynamoDB"
            
            expiration_time = response['Item']['otp']['expiration_time']['N']
            
            if int(expiration_time) > int(time.time()):
                return None, None, None, "Failed to resend OTP as it is not expired yet"  
            
        six_digit_otp = random.randint(100000, 999999)
        expiration_time = int(time.time()) + (2 * 60)

        # Save the OTP and expiration time in DynamoDB
        update_item = table.update_item(
            TableName='user',
            Key={
                'phone_number': phone_number,
                'country_code': country_code
            },
            UpdateExpression="SET otp.code = :otpCode, otp.expiration_time = :expiresAt",
            ExpressionAttributeValues={
                ':otpCode': {'S': six_digit_otp},
                ':expiresAt': {'N': str(expiration_time)}
            }
        )

        if update_item['ResponseMetadata']['HTTPStatusCode'] != 200:
            return None, None, None, "Failed to save OTP and expiration time in DynamoDB"

        # Publish the OTP to the phone number
        response = client.messages.create(
            attempt=max_retries,
            messaging_service_sid=os.environ['TWILIO_MESSAGING_SERVICE_SID'],
            body='[Image Verify] OTP Code: ' + str(six_digit_otp),
            to='+{}{}'.format(country_code, phone_number)
        )
        
        return response.sid, six_digit_otp, expiration_time, None

    except Exception as e:
        return None, None, None, str(e)
        
def build_response(statusCode, message, data=None, status_code=200):
    response = {
        "statusCode": statusCode,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        }
    }

    response["body"] = {
        "message": message,
        "status_code": status_code
    }

    if data is not None:
        response["body"]["data"] = data

    response["body"] = json.dumps(response["body"])
    return response