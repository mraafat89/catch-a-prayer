# 🕌 Catch a Prayer

Find nearby mosques and prayer times based on your location. Never miss a prayer again!

## Features

- **Location-based Mosque Discovery**: Find mosques within a configurable radius using Google Maps
- **Real-time Prayer Times**: Automatically scrape prayer times from mosque websites
- **Smart "Can Catch Prayer" Logic**: Calculates if you can reach a mosque before prayer time
- **Interactive Maps**: Visual mosque locations with travel time information
- **Responsive Design**: Mobile-optimized interface with clean, modern UI

## Architecture

### Backend (Python FastAPI)
- FastAPI with async support
- Google Maps API integration for mosque discovery and directions
- Web scraping for prayer time extraction
- Clean REST API with proper error handling

### Frontend (React TypeScript)
- React 18 with TypeScript for type safety
- Google Maps JavaScript API integration
- Tailwind CSS for modern, responsive design
- Axios for API communication

### Deployment
- Docker containerization with multi-stage builds
- Docker Compose orchestration
- Health checks and service dependencies
- Production-ready nginx configuration

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Google Maps API Key

### Environment Setup

1. Get a Google Maps API Key from [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Enable the following APIs:
   - Maps JavaScript API
   - Places API
   - Directions API

### Running the Application

```bash
# Clone the repository
git clone https://github.com/mraafat89/catch-a-prayer.git
cd catch-a-prayer

# Set your Google Maps API key in .env file
echo "GOOGLE_MAPS_API_KEY=your_api_key_here" > .env

# Start the application
docker-compose up --build

# Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Health Check: http://localhost:8000/health
```

## API Endpoints

- `GET /health` - Health check
- `POST /api/mosques/nearby` - Find nearby mosques
- `GET /api/settings` - Get user settings
- `PUT /api/settings` - Update user settings

## Development

### Backend Development
```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend Development
```bash
cd client
npm install
npm start
```

## Configuration

### Environment Variables
- `GOOGLE_MAPS_API_KEY` - Google Maps API key (required)
- `REACT_APP_API_URL` - Backend API URL (default: http://localhost:8000)

### User Settings
- Search radius (1-50 km)
- Prayer buffer time (arrival buffer in minutes)
- Display preferences (Adhan vs Iqama times)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

If you find this project helpful, please consider giving it a ⭐ on GitHub!

---

Built with ❤️ for the Muslim community