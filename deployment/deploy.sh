#!/bin/bash

# Catch a Prayer Deployment Script
set -e

echo "🕌 Deploying Catch a Prayer..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found. Please copy .env.example to .env and configure your Google Maps API key."
    exit 1
fi

# Check if Google Maps API key is set
if ! grep -q "GOOGLE_MAPS_API_KEY=.*[^=]" .env; then
    echo "❌ Error: GOOGLE_MAPS_API_KEY not set in .env file."
    echo "Please get your API key from https://console.cloud.google.com/apis/credentials"
    exit 1
fi

# Build and start services
echo "📦 Building and starting services..."
docker-compose down --remove-orphans
docker-compose up --build -d

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 30

# Check if services are running
echo "🔍 Checking service health..."

if curl -f http://localhost:8000/ > /dev/null 2>&1; then
    echo "✅ Backend API is running at http://localhost:8000"
else
    echo "❌ Backend API is not responding"
    docker-compose logs api
fi

if curl -f http://localhost:3000/ > /dev/null 2>&1; then
    echo "✅ Web app is running at http://localhost:3000"
else
    echo "❌ Web app is not responding"
    docker-compose logs web
fi

# Show logs
echo "📋 Recent logs:"
docker-compose logs --tail=20

echo ""
echo "🎉 Deployment complete!"
echo "🌐 Web App: http://localhost:3000"
echo "🔧 API: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo ""
echo "To stop the application, run: docker-compose down"
echo "To view logs, run: docker-compose logs -f"