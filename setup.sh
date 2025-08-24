#!/bin/bash
set -e

echo "🚀 Setting up Location Sharing Microservices..."

# Create directory structure
echo "📁 Creating directory structure..."
mkdir -p services/{java-auth,go-iot,python-socket}
mkdir -p k8s/{auth,iot,socket}
mkdir -p monitoring