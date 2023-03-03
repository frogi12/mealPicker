from __future__ import print_function
import pandas as pd
import numpy as np
import pickle, re, random, argparse, os.path, sys,requests, json
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/tasks']
notion_token = "38ebd3794b4cdc628bf37b32ed052f75e7b8d502ddc0a76b3fdf04800ce2abaec1ff84ac7c7946a4a306109c816b659a408fa5271fa6ed060cfd5401fb36f88e8878afb443fa98e1f66c19f0355b"

def computeUpTick():
	# load the data from a csv file
	data = pd.read_csv("meals.csv")
	
	# load the data into pandas' Series
	meals = data["Dish"]
	ingredients = data["Ingredients"]
	ingredientsList = data["Ingredients"].str.split(", ")
	freqScore = data["frequencyScore"]
	upTick = data["upTick"]
	
	# setup variables for the weighing
	N = len(meals)
	p_v = 1 / 2 # weight for the vegetarian meals
	p_h = 8 / 7 # weight for the more complicated meal
	meats = ["meat", "beef", "pork", "chicken", "bacon", "ham", "sausage", "steak"]
	
	# instantiate the variables for the number of  the various combinations of 
	# meal types
	veg_hard, veg_easy, meat_easy, meat_hard = 0, 0, 0, 0
	# indices of the specific meals
	veg_hard_i, veg_easy_i, meat_easy_i, meat_hard_i = [], [], [], [] 
	# count the meals with meat in them
	meat_meals = 0
	for meat in meats:
		meat_meals += ingredients.str.count(meat, re.I)
	
	hard_meals = ingredientsList.apply(lambda x: len(x) > 7)
	for i in range(N):
		if meat_meals[i] == 0 and hard_meals[i] == True:
			veg_hard += 1
			veg_hard_i.append(i)
		elif meat_meals[i] == 0 and hard_meals[i] == False:
			veg_easy += 1
			veg_easy_i.append(i)			
		elif meat_meals[i] != 0 and hard_meals[i] == True:
			meat_hard += 1
			meat_hard_i.append(i)
		else:
			meat_easy += 1
			meat_easy_i.append(i)
	# calculate the weight for the easy meals
	p_e = 1 / (meat_easy + veg_easy) * (N - (meat_hard + veg_hard) * p_h)
	# calculate the weight for the meat including meals
	p_m = (N - veg_hard * p_v * p_h - veg_easy * p_v * p_e) / (meat_easy * p_e + meat_hard * p_h)
	# update the the upticks of the meals
	upTick.update(pd.Series(
		[round(N / 5 * p_v * p_h, 2) for i in range(veg_hard)], index = veg_hard_i
	))
	upTick.update(pd.Series(
		[round(N / 5 * p_v * p_e, 2) for i in range(veg_easy)], index = veg_easy_i
	))
	upTick.update(pd.Series(
		[round(N / 5 * p_m * p_h, 2) for i in range(meat_hard)], index = meat_hard_i
	))
	upTick.update(pd.Series(
		[round(N / 5 * p_m * p_e, 2) for i in range(meat_easy)], index = meat_easy_i
	))
	
	output = pd.concat([meals, ingredients, freqScore, upTick], axis = 1)
	output.to_csv("meals.csv")



def offline():
	menu = pickMenu("meals.csv")
	
	#printing method for the meals and ingredients for each meal
	for i in range(len(menu[0])):
		print("Meal: {}".format(menu[0][i]))
		print("\tIngredients: "+", ".join(menu[1][i]))

def uploadTasks():
	menu = pickMenu("meals.csv")

	# google tasks integration
	creds = None
	# The file token.pickle stores the user's access and refresh tokens, and is
	# created automatically when the authorization flow completes for the first
	# time.
	pickleF = f'token_FoodPicker.pickle'
	if os.path.exists(pickleF):
		# open the file with the token and load the information
		with open(pickleF, 'rb') as token:
			creds = pickle.load(token)
	# ask for credentials if they are not valid
	if not creds or not creds.valid:
		# refresh th e credentials if they are expired
		if creds and creds.expired and creds.refresh_token:
			creds.refresh(Request())
		# connect to the server using the personal token
		else:
			flow = InstalledAppFlow.from_client_secrets_file('tokens/foodPickerCred.json', SCOPES)
			creds = flow.run_local_server()
			# Save the credentials for the next run
			with open(pickleF, 'wb') as token:
				pickle.dump(creds, token)
	# start the google tasks api
	service = build('tasks', 'v1', credentials=creds)
	# get the tasklist of the user
	tasklists = service.tasklists().list().execute()
	
	exists = False # boolean that stores if the tasklist "Menu for the week" exists
	menuID = "" # the id of the "Menu for the week" tasklist
	# check if the takslist "Menu for the Week" is in the task lists if yes store 
	# its tasklistID
	for tasklist in tasklists.get("items"):
		if tasklist["title"] == "Menu for the Week":
			exists = True
			menuID = tasklist["id"]
		else:
			pass
	
	menuAndFood = None
	# if tasklist "Menu for the Week" doesn't exist create it and save its tasklistID
	if menuID == "" and not exists: 
		menuAndFood = service.tasklists().insert(body = {"title": "Menu for the Week"}).execute()
		menuID = menuAndFood["id"]
	
	# start creating the menu list
	tasks = service.tasks().list(tasklist = menuID, maxResults = 100).execute()
	ingredID = ""
	
	# check if the "ingredientsToBuy" task was created if yes save its taskID if 
	# not create the task and save its ID
	if tasks.get("items") != None:
		for task in tasks.get("items"):
			if task["title"] == "ingredientsToBuy":
				ingredID = task.get("id")
				break
		page = tasks.get("nextPageToken")
		tasks = service.tasks().list(
			tasklist = menuID, pageToken = page, maxResults = 100
		).execute()
	
		while ingredID == "" and page != None:
			for task in tasks.get("items"):
				if task["title"] == "ingredientsToBuy":
					ingredID = task["id"]
					break
			tasks = service.tasks().list(
				tasklist = menuID, pageToken = page, maxResults = 100
			).execute()
			page = tasks.get("nextPageToken")
	
	if ingredID == "":
		ingredList = service.tasks().insert(
				tasklist = menuID, 
				body = {"title": "ingredientsToBuy"}
				).execute()
		ingredID = ingredList["id"]
	# instantiate the lists for ingredients and meals
	ingreds = []
	meals = []
	
	# go through the the added ingredients in the shopping list and append them to 
	# the ingerdient list to prevent douplicates
	tasks = service.tasks().list(tasklist = menuID, maxResults = 100).execute()
	page = tasks.get("nextPageToken")
	
	for task in tasks.get("items"):
		if task.get("parent") == ingredID:
			ingreds.append(task["title"])
		elif task.get("parent") == None:
			meals.append(task["title"])
		tasks = service.tasks().list(
			tasklist = menuID, pageToken = page, maxResults = 100
		).execute()
		page = tasks.get("nextPageToken")
	
	while page != None:
		for task in tasks.get("items"):
			if task.get("parent") == ingredID:
				ingreds.append(task["title"])
		tasks = service.tasks().list(
			tasklist = menuID, pageToken = page, maxResults = 100
		).execute()
		page = tasks.get("nextPageToken")
		
	for i in range(len(menu[0])):
		#add the meals from the picked menu to google tasks one by one
		if not menu[0][i] in meals:
			_ = service.tasks().insert( tasklist = menuID, body = {"title": menu[0][i]}).execute()
		# add the ingredients of the meals to the "ingredientsToBuy" task
		for j in range(len(menu[1][i])):
			#check if the ingredient has already been added to the task
			if not menu[1][i][j] in ingreds:
				_ = service.tasks().insert(
					tasklist = menuID,
					body = {"title": menu[1][i][j]},
					parent = ingredID
				).execute()
				#add the ingredient to the list of already written ingredients
				ingreds.append(menu[1][i][j])

def uploadNotion():
	menu = pickMenu("meals.csv")
	
#	token = "ask Karl"

#	database_id = "ed5a5dce5e36494f8e95ebb955ae21dc"
	
	token = "secret_w3VET7hX9wGuJAAtY3nHEIPUHEEHlO2ZwxfQKUBJIvm"

	database_id = "0090b32b3cfa4576a93807679b20d9be"
	
	headers = {
		"Authorization"		: "Bearer " + token,
		"Content-Type"		: "application/json",
		"Notion-Version"	: "2022-06-28"
	}
	
	for i in range(len(menu[0])):
		for j in range(len(menu[1][i])):
			create_page(database_id, headers, menu[1][i][j], menu[0][i])
	
	
def pickMenu(database):
	# load the data from a csv file
	data = pd.read_csv(database)
	
	# load the data into pandas' Series
	meals = data["Dish"]
	ingredients = data["Ingredients"]
	ingredientsList = data["Ingredients"].str.split(", ")
	freqScore = data["frequencyScore"]
	upTick = data["upTick"]
	
	# pick a random sample from the top 9 meals with the least frequency score
	pick = freqScore.take(freqScore.argsort()).head(9).sample(5).index
	# update the frequency score of the chosen meals by their respective uptick value and subtract 
	# one from the rest
	freqScore = freqScore.add(upTick.take(pick), fill_value = -1)
	freqScore.name = "frequencyScore"
	# combine the updated data and save it to the csv file
	output = pd.concat([meals, ingredients, freqScore, upTick], axis = 1)
	output.to_csv(database)
	# create a manu for the week with the list of ingredients
	menu = [meals.take(pick).array, ingredientsList.take(pick).array]
	return menu

def read_database(database_id, headers):
	read_url = f"https://api.notion.com/v1/databases/{database_id}/query"
	
	res = requests.request("POST", read_url, headers = headers)
	data = res.json()
	print(res.status_code)
	
	with open("./db.json", "w", encoding = "utf8") as f:
		json.dump(data, f, ensure_ascii = False)
	
def create_page(database_id, headers, name, tag):
	create_url = "https://api.notion.com/v1/pages"
	
	new_page_data = {
		"parent": { "database_id": database_id },	
		"properties": {
			"On List": {
				"id": "%5CW~U", 
				"type": "checkbox", 
				"checkbox": True}, 
			"Amount": {
				"id": "o%40HO", 
				"type": "rich_text", 
				"rich_text": []}, 
			"Tags": {
				"id": "p%7Deu", 
				"type": "multi_select", 
				"multi_select": [{
					"name": tag, 
					"color": "default"}]}, 
			"Name": {
				"id": "title", 
				"type": "title", 
				"title": [{
					"type": "text", 
					"text": {
						"content": name, 
						"link": None}, 
					"annotations": {
						"bold": False, 
						"italic": False, 
						"strikethrough": False, 
						"underline": False, 
						"code": False, 
						"color": "default"}, 
					"plain_text": name, 
					"href": None}]}}
	}
	
	data = json.dumps(new_page_data)
	
	res = requests.request("POST", create_url, headers = headers, data = data)
	
#	print(res.status_code)
#	print(res.text)
	
def update_page(database_id, headers, page_id):
	
	update_url = f"https://api.notion.com/v1/pages/{page_id}"
	
	update_data = {
		"properties": {
			"Tags": {
				"multi_select": [{
					"id": "6cbed006-4ba2-405a-be27-889f1f84b2b7", 
					"name": "no", 
					"color": "green"}]}}
	}
	
	data = json.dumps(update_data)
	
	res = requests.request("PATCH", update_url, headers = headers, data = data)
	
	print(res.status_code)
	print(res.text)

def main(argv):
	parser = argparse.ArgumentParser(
		description = "Meal picker a script that genrates a menu for the work week \
		based on given list of meals. It takes the dificulty and the environmental \
		inpact of the meals into account and suggests them less frequently."
	)
	parser.add_argument(
		"-u", "--calculate_uptick", action = "store_true", 
		help = "recalculate the uptick for the meals and store it to the csv \
		file with meals"
	)
	parser.add_argument(
		"-o", "--pick_menu_offline", action = "store_true", 
		help = "generate a five meal menu from the 7 meals with the lowest \
		frequency score and print it to the console"
	)
	parser.add_argument(
		"-n", "--upload_to_notion", action = "store_true",
		help = "generate a five meal menu from the 7 meals with the lowest \
		frequency score and add it to the notion database"
	)
	
	args = vars(parser.parse_args(argv))
	if args["calculate_uptick"]:
		print("You chose to calculate the uptick of the meals.")
		computeUpTick()
		print("Done.")
	else:
		if args["pick_menu_offline"]:
			print("You chose to generate the menu offline.")
			offline()
		elif args["upload_to_notion"]:
			print("You chose to generate the manu and upload it to notion.")
			uploadNotion()
		else:
			print("You chose to generate the menu and upload it to google tasks.")
			uploadTasks()
			print("Done.")
	
if __name__ == "__main__":
	main(sys.argv[1:])
