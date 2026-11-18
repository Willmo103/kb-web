# User Feedback: Obsidian Vault ZIP Export & Image Caching Pipeline

## Request Context
- **Date**: 2026-11-17
- **Branch**: `feature/obsidian-export-and-image-cache`
- **Prompt**:
  > Create an export mode wherin all articles and Youtube transcripts (exclude obsidian notes as it would be redundant) are exported as a single zipped folder with 2 sub-folders;
  > 1. `_sources` -- Will contain sub-folder for each source `site` with the raw markdown sourced from the urls as an individual file named in a format `'.'.join(url.path.parts.split('/'))`.md. The frontmatter of the md files will have the date it was scraped and its version
  > 2. `articles` -- sub-dirs in this folder are organized by collection then site. the generated wiki markdown will be saved in these folders will be saved as their title. where there are conflicts, a function will call the model to have a new title created (i think that this already happens on import...).
  >    I want full metadata in the frontmatter on the wikis to have the date scraped the site the model used.
  > I want all of the tags to be rendered on each document in the header area below the title in the proper obsidian format. I also want to create backlinks to the embedding nearest calculated neighbors (excluding the notes and shit that won't be included) all links should be local to the exported folder paths. assume that the `_sources` folder will be at `/` in the obsidian dir and the articles will be under `/reference/<articles>`
  >
  > Additional goal: Update the import process to cache all of the images on the page when fetching them. store these images as their hash as a key and their binary in the database, and keep a public asset folder synced from the database. replace the links on imports with the local images over time -- then in the future we can export the vault md with embedded base64 images (and display them on the page). IDK if it would be worth it to create a looping backfill proc but i think if the 'show original markdown' is clicked (or if its fetched when the page is loaded anyways) we could capture it..
  >
  > Full speed ahead, go go go . you have permission to do what ever you want, crush it. push all to prod when finished and commit merge that shit YO

## Directives & Approvals
- User granted explicit full-speed-ahead authorization to implement, test, document, commit, and push to `development` and `production`.
