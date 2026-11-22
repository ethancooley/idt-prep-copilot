#!/bin/bash
# Lambda handler: the Lambda Web Adapter runs this script, then forwards requests to the server.
PATH=$PATH:$LAMBDA_TASK_ROOT/bin PYTHONPATH=$LAMBDA_TASK_ROOT:$PYTHONPATH exec python -m idt_copilot.api.server
