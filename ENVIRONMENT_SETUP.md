# Environment Setup Guide

## 🔐 API Key Configuration

This application requires a Google Maps API key to function properly. **NEVER** commit API keys to version control!

### Step 1: Get Your Google Maps API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project or select an existing one
3. Enable the following APIs:
   - Maps JavaScript API
   - Places API
   - Geocoding API
   - Directions API
4. Create credentials (API Key)
5. Restrict your API key to prevent unauthorized usage:
   - Set application restrictions (HTTP referrers for web)
   - Set API restrictions (only enable needed APIs)

### Step 2: Configure Environment Variables

#### Server Configuration
Create `server/.env` file:
```bash
# Copy from .env.example and update with your key
cp .env.example server/.env
```

Edit `server/.env`:
```env
GOOGLE_MAPS_API_KEY=your_actual_api_key_here
```

#### Client Configuration  
Create `client/.env` file:
```env
REACT_APP_GOOGLE_MAPS_API_KEY=your_actual_api_key_here
REACT_APP_API_URL=http://localhost:8000
```

### Step 3: Verify Setup

1. Check that `.env` files are in `.gitignore` (they are!)
2. Run the application:
   ```bash
   docker-compose up --build
   ```
3. If you see errors about missing API keys, double-check your `.env` files

## 🚫 Security Best Practices

- ✅ Store API keys in `.env` files (ignored by git)
- ✅ Use environment variables in code: `process.env.GOOGLE_MAPS_API_KEY`
- ✅ Restrict API keys in Google Cloud Console
- ❌ Never hardcode API keys in source code
- ❌ Never commit `.env` files to version control
- ❌ Never share API keys in public channels

## 📁 File Structure

```
├── server/
│   ├── .env                 # Server environment variables (DO NOT COMMIT)
│   └── ...
├── client/
│   ├── .env                 # Client environment variables (DO NOT COMMIT)  
│   └── ...
├── .env.example             # Template file (safe to commit)
├── .gitignore               # Excludes .env files from git
└── docker-compose.yml       # References env_file settings
```

## 🔧 Troubleshooting

**Problem**: "Google Maps API key is not configured"
**Solution**: Ensure `.env` files exist with correct variable names

**Problem**: Maps not loading
**Solution**: Check browser console for API key errors, verify API is enabled in Google Cloud

**Problem**: Build fails with API key errors  
**Solution**: Verify `docker-compose.yml` env_file paths are correct