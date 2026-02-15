# Directory Setup
brew install node
touch Dockerfile
touch .dockerignore
touch .gitignore
touch README.md
touch LICENSE
mkdir misc frontend backend
cd backend && touch .env && touch lambda_function.py && touch requirements.txt && python3.11 -m venv .venv/ && source .venv/bin/activate && pip install --upgrade pip setuptools wheel&& pip install ipykernel jupyter && ipython kernel install --user --name=Gov-Alt-venv --display-name=Gov-Alt-venv
npm create vite@latest frontend -- --template react
cd frontend && npm install && rm -rf .gitignore && rm -rf README.md && rm -rf src/assets && mkdir src/assets && rm -rf public && mkdir public && rm -rf src/assets/App.css && touch src/assets/App.css && rm -rf src/assets/App.jsx && touch src/assets/App.jsx && npm install react-bootstrap bootstrap && npm i bootstrap-icons
npm run dev


# GCP Build
gcloud 

gcloud run deploy search-in-firestore \
  --source . \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated

gcloud run services update search-in-firestore \
  --region asia-northeast1 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=gov-alternate,\
DATABASE_ID=gov-secretary,\
COLLECTION_ID=catalogs,\
CATALOG_ID=2c5f9141-f747-4a08-9ff7-ee11503e06d8,\
SUBCOLLECTION_ID=programs,\
GEMINI_API_KEY=xxx"

gcloud run deploy cr-gov-sec \
  --source . \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated

gcloud run services update cr-gov-sec \
  --region asia-northeast1 \
  --env-vars-file env.yaml

gcloud run services logs read cr-gov-sec --region asia-northeast1 --limit 10

# GitHub Setup
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/akira-c-k/Gov-Alternate.git
git push -u origin main