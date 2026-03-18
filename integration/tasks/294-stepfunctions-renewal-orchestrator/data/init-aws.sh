#!/bin/bash

# This script is used to create prereq infrastructure for on localstack
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test

# for now, just confirm that the awscli can talk to the localstack
awslocal s3 ls