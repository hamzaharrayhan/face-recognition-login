#!/bin/sh

# Load environment variables from .env file
if [ -f "${LAMBDA_TASK_ROOT}/.env" ]; then
    export $(cat ${LAMBDA_TASK_ROOT}/.env | grep -v '^#' | xargs)
fi

# Execute the Python Lambda function handler
exec python -m awslambdaric "$@"