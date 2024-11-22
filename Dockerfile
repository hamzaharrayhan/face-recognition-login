# Use the official AWS Lambda Python 3.9 base image
FROM public.ecr.aws/lambda/python:3.9

# Install OS-level dependencies
RUN yum -y groupinstall "Development Tools" && \
    yum -y install cmake && \
    yum -y install openssl-devel

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install pillow
RUN pip install numpy==1.26.4

# Install dlib from source
RUN curl -O http://dlib.net/files/dlib-19.22.tar.bz2 && \
    tar xvf dlib-19.22.tar.bz2 && \
    cd dlib-19.22 && \
    python setup.py install && \
    cd .. && \
    rm -rf dlib-19.22 dlib-19.22.tar.bz2


RUN pip install opencv-python-headless numpy

# Install face_recognition
RUN pip install face_recognition

RUN pip install requests-toolbelt
RUN pip install twilio
RUN pip install awslambdaric
RUN pip install boto3

COPY .env ${LAMBDA_TASK_ROOT}/.env
COPY app.py ${LAMBDA_TASK_ROOT}
COPY lambda-entrypoint.sh /lambda-entrypoint.sh

# Make the entrypoint script executable
RUN chmod +x /lambda-entrypoint.sh

# Set the ENTRYPOINT to ensure the handler name is the first argument
ENTRYPOINT ["/lambda-entrypoint.sh"]
CMD ["app.lambda_handler"]
