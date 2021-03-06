#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import re
import random
import hashlib
import hmac
from string import letters
import pdb
import code

import webapp2
import jinja2

from google.appengine.ext import db

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = \
    jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir),
                       autoescape=True)

secret = 'fart'


def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)


def make_secure_val(val):
    return '%s|%s' % (val, hmac.new(secret, val).hexdigest())


def check_secure_val(secure_val):
    val = secure_val.split('|')[0]
    if secure_val == make_secure_val(val):
        return val


class BlogHandler(webapp2.RequestHandler):

    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def render_str(self, template, **params):
        params['user'] = self.user
        return render_str(template, **params)

    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header('Set-Cookie', '%s=%s; Path=/'
                                         % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        return cookie_val and check_secure_val(cookie_val)

    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    def logout(self):
        self.response.headers.add_header('Set-Cookie',
                                         'user_id=; Path=/')

    def initialize(self, *a, **kw):
        webapp2.RequestHandler.initialize(self, *a, **kw)
        uid = self.read_secure_cookie('user_id')
        self.user = uid and User.by_id(int(uid))


def render_post(response, post):
    response.out.write('<b>' + post.subject + '</b><br>')
    response.out.write(post.content)


class MainPage(BlogHandler):

    def get(self):
        self.redirect('/blog')


def make_salt(length=5):
    return ''.join(random.choice(letters) for x in xrange(length))


def make_pw_hash(name, pw, salt=None):
    if not salt:
        salt = make_salt()
    h = hashlib.sha256(name + pw + salt).hexdigest()
    return '%s,%s' % (salt, h)


def valid_pw(name, password, h):
    salt = h.split(',')[0]
    return h == make_pw_hash(name, password, salt)


def users_key(group='default'):
    return db.Key.from_path('users', group)


def blog_key(name='default'):
    return db.Key.from_path('blogs', name)


# Entities

class User(db.Model):

    name = db.StringProperty(required=True)
    pw_hash = db.StringProperty(required=True)
    email = db.StringProperty()

    @classmethod
    def by_id(cls, uid):
        return User.get_by_id(uid, parent=users_key())

    @classmethod
    def by_name(cls, name):
        u = User.all().filter('name =', name).get()
        return u

    @classmethod
    def register(
        cls,
        name,
        pw,
        email=None,
    ):
        pw_hash = make_pw_hash(name, pw)
        return User(parent=users_key(), name=name, pw_hash=pw_hash,
                    email=email)

    @classmethod
    def login(cls, name, pw):
        u = cls.by_name(name)
        if u and valid_pw(name, pw, u.pw_hash):
            return u


class Post(db.Model):

    owner = db.ReferenceProperty(User)
    subject = db.StringProperty(required=True)
    content = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    last_modified = db.DateTimeProperty(auto_now=True)

    def render(self):
        self._render_text = self.content.replace('\n', '<br>')
        return render_str('post.html', p=self)


class Like(db.Model):

    owner = db.ReferenceProperty(User)
    post = db.ReferenceProperty(Post, collection_name='likes')
    liked = db.BooleanProperty(default=False)


class Comment(db.Model):

    post = db.ReferenceProperty(Post, collection_name='comments')
    author = db.ReferenceProperty(User)
    content = db.StringProperty(required=True, multiline=True)
    created = db.DateTimeProperty(auto_now_add=True)


# Post Actions

class BlogFront(BlogHandler):

    def get(self):
        posts = greetings = Post.all().order('-created')
        self.render('front.html', posts=posts)


class NewPost(BlogHandler):

    def get(self):
        if self.user:
            self.render('newpost.html')
            return
        else:
            self.redirect('/login')
            return

    def post(self):
        if not self.user:
            self.redirect('/login')
            return
        owner = self.user
        subject = self.request.get('subject')
        content = self.request.get('content')

        if subject and content and owner:
            p = Post(parent=blog_key(), subject=subject,
                     content=content, owner=owner)
            p.put()
            self.redirect('/blog/%s' % str(p.key().id()))
        else:
            error = 'subject and content, please!'
            self.render('newpost.html', subject=subject,
                        content=content, error=error)


class EditPostPage(BlogHandler):

    def get(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)
            if post is not None:
                userkey = db.Key.from_path('User', self.user.name)
                ownerkey = db.Key.from_path('User', post.owner.name)
                if self.user.key().id() == post.owner.key().id():
                    self.render('editpost.html', post=post)
                else:
                    error = 'You cannot edit a post that is not yours!'
                    self.render('permalink.html', post=post,
                                comments=post.comments, error=error)
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')

    def post(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)
            if post is not None:
                post.content = self.request.get('content')
                post.subject = self.request.get('subject')
                if self.user.key().id() == post.owner.key().id():
                    post.put()
                    self.redirect('/blog/' + post_id)
                else:
                    error = "This is not your post!"
                    self.render('permalink.html', error=error,
                                post=post, comments=post.comments)
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')


class PostPage(BlogHandler):

    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)
        comments = post.comments
        if not post:
            self.error(404)
            return
        self.render('permalink.html', post=post, comments=comments)


class DeletePostPage(BlogHandler):

    def get(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id),
                                   parent=blog_key())
            post = db.get(key)
            if post is not None:
                userkey = db.Key.from_path('User', self.user.name)
                ownerkey = db.Key.from_path('User', post.owner.name)
                if self.user.key().id() == post.owner.key().id():
                    post.delete()
                else:
                    error = \
                        'You cannot delete this post because it is not yours!'
                    self.render('permalink.html', post=post, error=error,
                                comments=post.comments)
                    return
                self.redirect('/blog')
                return
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')


class LikePost(BlogHandler):

    def get(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id),
                                   parent=blog_key())
            post = db.get(key)
            if post is not None:
                owner = self.user
                if self.user.key().id() != post.owner.key().id():
                    postlikes = post.likes
                    for p in postlikes:
                        if p.owner.name == self.user.name:
                            p.liked = not p.liked
                            p.put()
                            self.redirect('/blog/' + post_id)
                            return
                    like = Like(parent=blog_key(), post=post,
                                owner=self.user, liked=True)
                    like.put()
                    self.redirect('/blog/' + post_id)
                    return
                else:
                    error = "You can't like your own post!"
                    self.render('permalink.html', post=post,
                                comments=post.comments, error=error)
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')


# Comment Actions

class AddComment(BlogHandler):

    def get(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id),
                                   parent=blog_key())
            post = db.get(key)
            if post is not None:
                self.render('comment.html', post=post)
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')

    def post(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)
            if post is not None:
                content = self.request.get('comment')
                author = self.user
                c = Comment(parent=blog_key(), content=content, author=author,
                            post=post)
                c.put()
                self.redirect('/blog/' + post_id)
                return
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')


class DeleteComment(BlogHandler):

    def get(self, comment_id):
        if self.user:
            key = db.Key.from_path('Comment', int(comment_id),
                                   parent=blog_key())
            comment = db.get(key)
            if comment is not None:
                userkey = db.Key.from_path('User', self.user.name)
                ownerkey = db.Key.from_path('User', comment.author.name)
                post = comment.post
                if self.user.key().id() == comment.author.key().id():
                    comment.delete()
                    self.redirect('/blog/' + str(post.key().id()))
                else:
                    error = \
                        'You cannot delete this comment because it is' + \
                        'not yours!'
                    self.render('permalink.html', post=post, error=error,
                                comments=post.comments)
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')


class EditComment(BlogHandler):

    def get(self, comment_id):
        if self.user:
            key = db.Key.from_path('Comment', int(comment_id),
                                   parent=blog_key())
            comment = db.get(key)
            if comment is not None:
                userkey = db.Key.from_path('User', self.user.name)
                ownerkey = db.Key.from_path('User', comment.author.name)
                post = comment.post
                print self.user.key().id()
                print comment.author.key().id()
                if self.user.key().id() == comment.author.key().id():
                    self.render('editcomment.html', post=post,
                                comment=comment)
                else:
                    error = 'You cannot edit this comment because it is' + \
                            'not yours!'
                    self.render('permalink.html', post=post, error=error,
                                comments=post.comments)
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')

    def post(self, comment_id):
        if self.user:
            key = db.Key.from_path('Comment', int(comment_id),
                                   parent=blog_key())
            comment = db.get(key)
            if comment is not None:
                if self.user.key().id() == comment.author.key().id():
                    comment.content = self.request.get('content')
                    comment.put()
                    post_id = self.request.get('post_id')
                    self.redirect('/blog/' + post_id)
                else:
                    error = "This comment is not yours!"
                    self.redirect('permalink.html', post=comment.post,
                                  comments=comment.post.comments, error=error)
                    return
            else:
                self.redirect('/blog')
        else:
            self.redirect('/login')


# Unit 2 HW's

class Rot13(BlogHandler):

    def get(self):
        self.render('rot13-form.html')

    def post(self):
        rot13 = ''
        text = self.request.get('text')
        if text:
            rot13 = text.encode('rot13')

        self.render('rot13-form.html', text=rot13)


USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")


def valid_username(username):
    return username and USER_RE.match(username)


PASS_RE = re.compile(r"^.{3,20}$")


def valid_password(password):
    return password and PASS_RE.match(password)


EMAIL_RE = re.compile(r'^[\S]+@[\S]+\.[\S]+$')


def valid_email(email):
    return not email or EMAIL_RE.match(email)


class Signup(BlogHandler):

    def get(self):
        self.render('signup-form.html')

    def post(self):
        have_error = False
        self.username = self.request.get('username')
        self.password = self.request.get('password')
        self.verify = self.request.get('verify')
        self.email = self.request.get('email')

        params = dict(username=self.username, email=self.email)

        if not valid_username(self.username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not valid_password(self.password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif self.password != self.verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not valid_email(self.email):
            params['error_email'] = "That's not a valid email."
            have_error = True

        if have_error:
            self.render('signup-form.html', **params)
        else:
            self.done()

    def done(self, *a, **kw):
        raise NotImplementedError


class Unit2Signup(Signup):

    def done(self):
        self.redirect('/unit2/welcome?username=' + self.username)


class Register(Signup):

    def done(self):

        # make sure the user doesn't already exist

        u = User.by_name(self.username)
        if u:
            msg = 'That user already exists.'
            self.render('signup-form.html', error_username=msg)
        else:
            u = User.register(self.username, self.password, self.email)
            u.put()

            self.login(u)
            self.redirect('/blog')


class Login(BlogHandler):

    def get(self):
        self.render('login-form.html')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        u = User.login(username, password)
        if u:
            self.login(u)
            self.redirect('/blog')
        else:
            msg = 'Invalid login'
            self.render('login-form.html', error=msg)


class Logout(BlogHandler):

    def get(self):
        self.logout()
        self.redirect('/blog')


class Unit3Welcome(BlogHandler):

    def get(self):
        if self.user:
            self.render('welcome.html', username=self.user.name)
        else:
            self.redirect('/signup')


class Welcome(BlogHandler):

    def get(self):
        username = self.request.get('username')
        if valid_username(username):
            self.render('welcome.html', username=username)
        else:
            self.redirect('/unit2/signup')


app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/unit2/rot13', Rot13),
    ('/unit2/signup', Unit2Signup),
    ('/unit2/welcome', Welcome),
    ('/blog/?', BlogFront),
    ('/blog/([0-9]+)', PostPage),
    ('/blog/newpost', NewPost),
    ('/signup', Register),
    ('/login', Login),
    ('/logout', Logout),
    ('/unit3/welcome', Unit3Welcome),
    ('/blog/edit/([0-9]+)', EditPostPage),
    ('/blog/delete/([0-9]+)', DeletePostPage),
    ('/blog/like/([0-9]+)', LikePost),
    ('/blog/comment/([0-9]+)', AddComment),
    ('/blog/DeleteComment/([0-9]+)', DeleteComment),
    ('/blog/EditComment/([0-9]+)', EditComment),
], debug=True)
