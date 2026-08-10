# Open Issues

---

## 8. Views are too cramped

The collection views for the agent, adding items, and management are all too cramped horizontally. The agent view is barely wide enough to fit the label text for the agent selection, this is also true for other views in the web app. I want to adjust the column widths of all of the columns so that it is much more reactive and displays more of the information. Screen shots will be attached for these issues.

---

## 7. API Keys are not viewable when created

When registering the new clients in the admin portal, the keys are saved to the database and displayed with the `...` omitting the actual key value; I need to be able to copy the key to my clipboard via a button click (so as to keep the value private, but also allowing me to get the value without having to go searching for the client in the database).

---

## 6. CLI should expose server logs

I want a command in the CLI to view the server logs as I would be able to view inside of the admin view of the UI. This command should allow you to enter a number of lines to display. The default number of lines should be 100. The last chosie of number of lines should be remembered, so that when the page is refreshed the same amount of lines are displayed.

The list should be reverse sorted so that the most current logs are displayed on top, avoiding the need to scroll to the bottom of the page to view the most recent logs.
