# LANHub
Change REPO_URL under "glob_vars.py" for deployment

To Install dependencies within a venv, use:
```bash
pip install -r dependencies.txt
```

Setup ssh for the static page:
```bash
ssh-keygen -t ed25519 -C "theplatecrafter@gmail.com"
```
then 
```bash
cat ~/.ssh/id_ed25519.pub
```
to copy the SSH key and paste into a new SSH in your github account settings
Then, switch this repo from html to ssh
```bash
git remote set-url origin git@github.com:theplatecrafter/LANHub-redirector-dev.git
```