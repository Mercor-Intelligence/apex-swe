#!/bin/bash

# This script is used to create prereq infrastructure for on localstack
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test

# Create SQS queue for S3 event notifications
awslocal sqs create-queue --queue-name file-upload-queue

# Confirm that the awscli can talk to the localstack
awslocal s3 ls