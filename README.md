# Dresser - AI Closet / Stylist App

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your OpenAI API key:
   
   **Option 1: Using a .env file (Recommended)**
   
   Create a `.env` file in the project root:
   ```
   OPENAI_API_KEY=your-api-key-here
   ```
   
   The code will automatically load this file using `python-dotenv`.
   
   **Option 2: Environment variable**
   ```bash
   # Windows PowerShell
   $env:OPENAI_API_KEY="your-api-key-here"
   
   # Linux/Mac
   export OPENAI_API_KEY="your-api-key-here"
   ```

3. Place a test outfit image at `Images/test_outfit.jpg`

## Running the Integration Test

Run the full pipeline test:
```bash
pytest tests/integration/test_clothing_pipeline.py -v
```

The test will:
- Detect all clothing items in the outfit image
- Generate product-style images for each item
- Get brand/store metadata for each item
- Save results to the `Responses/` folder:
  - Individual product images (PNG files)
  - `items_summary.json` - Complete JSON summary
  - `items_summary.txt` - Human-readable text summary

## Project Structure

```
Dresser0.2/
├── app/
│   ├── services/
│   │   └── clothing_pipeline.py  # Main pipeline service
├── tests/
│   └── integration/
│       └── test_clothing_pipeline.py  # Integration test
├── Images/  # Place test outfit images here
├── Responses/  # Generated images and summaries go here
└── requirements.txt
```

## Note on Model Names

The code uses `gpt-4o-mini` for vision tasks and `dall-e-3` for image generation, which are the current OpenAI models. If you need to use different model names, update them in `app/services/clothing_pipeline.py`.

