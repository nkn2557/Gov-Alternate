# Project-Charter
Create: 2025-12-26<br>
Update: 2025-12-27

## Product
- [URL]()

## Name of Project
- Temporary
    - EN: Gov-Secretary, Gov-Alternate
    - JA: 役所代行, 行政秘書
- Production
    - EN: xxx
    - JA: xxx

## Objective ~ Solution
- Why   : The website of each government aren't integrated in the terms of UI/UX, and we have to download and write many documents.
- Who   : Everybody who has to be involved with the goverment at each life-event.
- What  : The product can collect information with integrated UI and make the example for documents.
- How
    - Frontend
        - user can select which goverment or district that he/she has to be involved with
        - user can input/select what (category) he/she want to know
        - user can get the text/graphic information that he/she want to know ot he/she have to do
        - user may submit invidiual information that be input in the documents 
        - user may download the documents that he/she had to write down
    - Backend
        - RAG
            - Temporary / permanent database of text information written on each gov-websites
            - Access each gov-websites directly
        - Examine that submittion of RAG is right
        - Cleanse user information and request more information that be required for the documents
        - Make the documents and submit for download-file

## [Schedule](https://zenn.dev/hackathons/google-cloud-japan-ai-hackathon-vol4?tab=schedule)
- Register and Submittion: Dec10 ~ Feb15
- First examination: Feb16 ~ Feb23
- Second examination: Feb24 ~ Mar2
- Notification: Mar2

## Responsibilities
- Backend       : Nakano, Irikuchi
- Forntend      : Mashiko, Komori
- Server        : Komori
- Presentation  : Mashiko

## Architecture
- be going to make in draw.io ..

## Environment
- Tool
    - Editor    : VSCode
    - Browsor   : Google Chrome / Safari
    - Sharing   : Github / Notion
    - Deploy    : CloudFlare
    - Server    : GCP
    - Design    : Canva / Figma
- Code
    - Backend   : Python3.11 
    - Frontend  : React + Vite
- Test
    - Localhost
    - Postman

## Directory
- backend   : test.ipynb, venv-environment, other .py files, etc.
- docs      : Document for settings, memo, etc.
- frontend  : App.jsx, App.css, assets, etc.

## Reference
- [第4回 Agentic AI Hackathon with Google Cloud](https://zenn.dev/hackathons/google-cloud-japan-ai-hackathon-vol4?tab=overview)