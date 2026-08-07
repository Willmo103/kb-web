# Issues

Issues in this document that have their text ~~struck through~~ are considered completed. The newest issues will be added at the *top* of this markdown document.


- The export proces should also include an option to download the saved videos
 - I want to be able to export and import the entire datset from the UI

- I want to modify the server to be able to upload and parse files (like pdfs, code, word docs, etc. and have them stored and wiki generated for them as I am for webpages and videos
---

## ~~Create A CLI for interacting with the LIVE server~~

~~@feature-request~~

~~I would like a CLI and accompanying API router in the application to expose *admin* tasks to the CLI. The CLI will use an `X-API-KEY` header in the request to pass an API key that is generated from the `admin portal` to register clients with their computer names.~~

~~I want to add commands to the CLI to do the following:~~

~~**general**~~
~~- Install the CLI~~
~~- List available commands~~
~~- Help for specific commands~~
~~**API Interactions**~~
~~- post url's to the server for processing~~
~~- list `n` number of most recent articles/videos~~
~~- triggure any of the privlaged functions for a specific article or video (regenerate-wiki, download-video, regenerate-tags, etc.)~~
~~- list available collections and their item counts~~
~~- trigger collection operations such as adding and removing items from collections~~
~~- list all tags~~
~~- triggure tag operations~~
~~- **query an agent with tools to search and retrieve context from the knowledge base**~~

---

## ~~`Cloud Stream` displays on all videos in the `/view/page` endpoint~~
~~@bugfix~~

~~All videos, regardless of whether the video has been downloaded to the server or not, they display the `Cloud Stream` badge.~~

---

## ~~Collection orginization is skewed and broken~~
~~@bugfix~~

~~The logic for collections created when a URL is being imported is *entirely* detatched from the actual collection logic of the application. This issue manifests in the following ways:~~

- ~~If a collection is *created* from the /import screen, that collection does not get created in the collection business logic.~~
- ~~The badge that articles carry when assigned a collection at import display, but the other collection organizational attributes do not (parent/child relationships, etc. )~~
- ~~I cannot place any items in a collection using the /collections page; they do not display *at all* in the list of collections~~
- ~~**No** collection information is displayed on videos *at all*, not even the badge that is displayed on articles or any buttons that allow for videos to be placed in a collection appear on the video page *at all*. They may be added from the /collection management page, but they display as simple cards.~~

---

## ~~Server Log Display Issues~~
~~@bugfix~~

~~The following changes need to be made to the server log interface:~~

- ~~The server logs should be reverse sorted so that the most current logs are displayed on to to aviod scrolling to the bottom for the most recent~~
- ~~The choice for default amount of lines should be set to 100 lines~~
- ~~The last choice of "number of lines to display" should be remembered, so that when the page is refreshed the same amount of lines are displayed~~

---

## ~~Server Configurations for Agent System Messages are not being saved~~
~~@bugfix~~

~~The admin portal page has some issues with persistance including the Agent system messages for the various agents (Wiki generator and YouTube transcript generator). The changes to the prompt are not being saved or updated when the save button is perssed. After making a change, when the page is updated, the prompts return to the former prompt.~~

~~To address this issue and future-proof further configurations, The following changes are being requested:~~

- ~~All configurations should be moved to the database as either multiple related settings tables, or many standalone tables.~~
 - ~~Like-options should be grouped together in a single table~~
 - ~~Agent prompts should be versioned so that the admin portal may:~~
  - ~~display a historical record of prompts~~
  - ~~allow for reversion to previous prompts~~
  - ~~curate a collection of prompts; allowing a prompt to be chosen as the HEAD prompt.~~
- ~~Admin Portal should be ubdated to accomidate the proposed changes.~~

---
