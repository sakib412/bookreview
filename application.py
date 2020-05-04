import os

from flask import Flask, render_template, session, redirect, request, jsonify, flash, url_for
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
import requests
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))


@app.route("/")
def index():
    user_name = session.get("user_name")

    if user_name:

        book = db.execute("SELECT * FROM books LIMIT 9").fetchall()
        #res = requests.get("https://www.goodreads.com/book/review_counts.json", params={"key": "KEY", "isbns": "9781632168146"})

        return render_template("index.html", books=book)

    else:
        return redirect(url_for("login", message="You must Login"))


@app.route("/logout")
def logout():
    session.clear()

    return redirect(url_for("login", message="logged out succesfully"))


@app.route("/login", methods=["POST", "GET"])
def login():
    user_name = session.get("user_name")
    if user_name:
        return redirect("/")

    message = request.args.get("message")
    if message:
        return render_template("login.html", message=message)
    if request.method == "POST":
        if not request.form.get("username"):
            return render_template("login.html", message="Please input your Username")
        if not request.form.get("password"):
            return render_template("login.html", message="PLease input your Password")
        username = request.form.get("username")
        password = request.form.get("password")
        rows = db.execute(
            "SELECT * FROM users WHERE username = :username", {"username": username})

        result = rows.fetchone()
        if result == None or not check_password_hash(result.password, password):
            return render_template("login.html", message="invalid username and/or password")
        session["user_id"] = result.id
        session["user_name"] = result.fullname

        return redirect("/")
    else:
        layout = render_template("login.html")
        return f"{layout}"



@app.route("/register", methods=["GET", "POST"])
def register():

    user_id = session.get("user_name")
    if user_id:
        return redirect("/")

    if request.method == "POST":
        if not request.form.get("fullname"):
            return render_template("register.html", message="must provide fullname")

        if not request.form.get("username"):
            return render_template("register.html", message="must provide username")

        # Query database for username and mail
        userCheck = db.execute("SELECT * FROM users WHERE username = :username",
                               {"username": request.form.get("username")}).fetchone()

        # Check if username already exist
        if userCheck:
            return render_template("register.html", message="username already exist")

        mailCheck = db.execute("SELECT * FROM users WHERE email = :email",
                               {"email": request.form.get("email")}).fetchone()

        if mailCheck:
            return render_template("register.html", message="email already exist")

        # Ensure password was submitted
        elif not request.form.get("pwd1"):
            return render_template("register.html", message="must provide password")

        elif not request.form.get("pwd2"):
            return render_template("register.html", message="must confirm password")

        elif not request.form.get("pwd1") == request.form.get("pwd2"):
            return render_template("register.html", message="password didn't match")

        # Hash user's password to store in DB
        hashedPassword = generate_password_hash(request.form.get(
            "pwd2"), method='pbkdf2:sha256', salt_length=8)
        fullname = request.form.get("fullname")

        db.execute("INSERT INTO users (fullname, username, email, password ) VALUES (:fullname, :username, :email, :password)",
                   {"fullname": fullname,
                    "username": request.form.get("username"),
                    "email": request.form.get("email"),
                    "password": hashedPassword})

        db.commit()

        flash('Account created', 'info')

        return redirect(url_for("login", message="registration succesfull!! login with your username and password"))

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")



@app.route("/search", methods=["GET"])
def search():
    user_id = session.get("user_name")

    if user_id:

        # Check book id was provided
        if not request.args.get("book"):
            return render_template("result.html", message="you must input title, author or isbn.")

        # Take input and add a wildcard
        query = "%" + request.args.get("book") + "%"

        query = query.title()

        rows = db.execute("SELECT isbn, title, author, year FROM books WHERE \
                            isbn LIKE :query OR \
                            title LIKE :query OR \
                            author LIKE :query LIMIT 20",
                          {"query": query})

        # Books not founded
        if rows.rowcount == 0:
            return render_template("result.html", message="can't find books with that information.")

        # Fetch all the results
        books = rows.fetchall()

        return render_template("result.html", books=books)
    else:
        return redirect(url_for("login", message="you must login"))

@app.route("/book/<isbn>", methods=['GET', 'POST'])
def book(isbn):
    user_id = session.get("user_name")
    if user_id:

        if request.method == "POST":
            currentUser = session["user_id"]

            rating = request.form.get("rating")
            comment = request.form.get("comment")

            # Search book_id by ISBN
            row = db.execute("SELECT id FROM books WHERE isbn = :isbn",
                             {"isbn": isbn})

            # Save id into variable
            bookId = row.fetchone()
            bookId = bookId.id

            # Check for user submission (ONLY 1 review/user allowed per book)
            row2 = db.execute("SELECT * FROM reviews WHERE user_id = :user_id AND book_id = :book_id",
                              {"user_id": currentUser,
                               "book_id": bookId})

            # A review already exists
            if row2.rowcount == 1:

                flash('You already submitted a review for this book', 'warning')
                return redirect("/book/" + isbn)

            # Convert to save into DB
            rating = int(rating)

            db.execute("INSERT INTO reviews (user_id, book_id, comment, rating) VALUES \
                        (:user_id, :book_id, :comment, :rating)",
                       {"user_id": currentUser,
                        "book_id": bookId,
                        "comment": comment,
                        "rating": rating})

            # Commit transactions to DB and close the connection
            db.commit()

            flash('Review submitted!', 'info')

            return redirect("/book/" + isbn)

        # Take the book ISBN and redirect to his page (GET)
        else:

            row = db.execute("SELECT id, isbn, title, author, year FROM books WHERE \
                            isbn = :isbn",
                             {"isbn": isbn})

            bookInfo = row.fetchall()

            """ GOODREADS reviews """

            # Read API key from env variable
            key = os.getenv("KEY")

            # Query the api with key and ISBN as parameters
            query = requests.get("https://www.goodreads.com/book/review_counts.json",
                                 params={"key": key, "isbns": isbn})
            if not query:
                return redirect(url_for('index'))

            response = query.json()



            # "Clean" the JSON before passing it to the bookInfo list
            response = response['books'][0]

            # Append it as the second element on the list. [1]
            bookInfo.append(response)

            # Search book_id by ISBN
            row3= db.execute("SELECT id FROM books WHERE isbn= :isbn", {"isbn": isbn})
            result3= row3.fetchone()
         

            # Save id into variable
          
            book = result3['id']

            results= db.execute("SELECT fullname, rating, comment, to_char(time, 'DD Mon YY - HH24:MI:SS') as time FROM users INNER JOIN reviews ON users.id=reviews.user_id WHERE book_id= :book ORDER BY time",{"book": book})
            reviews = results.fetchall()

            return render_template("book.html", bookInfo=bookInfo, reviews= reviews)
    else:
        flash('you must login to see book','warning')
        return redirect(url_for('login', message= "you must login to see book"))



@app.route("/api/<isbn>", methods=['GET'])
def api_call(isbn):
        user_name = session.get("user_name")

        if user_name:


            row = db.execute("SELECT title, author, year, isbn, \
                        COUNT(reviews.id) as review_count, \
                        AVG(reviews.rating) as average_score \
                        FROM books \
                        INNER JOIN reviews \
                        ON books.id = reviews.book_id \
                        WHERE isbn = :isbn \
                        GROUP BY title, author, year, isbn",
                        {"isbn": isbn})

        
            if row.rowcount != 1:

                return jsonify({"Error": "Invalid book ISBN"}), 404
  
            ap1 = row.fetchone()

            # Convert to dict
            result = dict(ap1.items())



            result['average_score'] = float('%.2f'%(result['average_score']))

            return jsonify(result)
        else:
            flash('you must login to see api','warning')
            return redirect(url_for('login', message= "you must login to see api"))