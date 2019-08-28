#!/usr/bin/env python3
import os
import sys
import numpy as np
import argparse
import hashlib
import pylab as plt
import tensorflow as tf

from common import MySQL, Languages, Timer
from helpers import Env, Link

######################################################################################
class LearningParams:
    def __init__(self, languages, saveDir, saveDirPlots, deleteDuplicateTransitions, langPair):
        self.gamma = 0.999
        self.lrn_rate = 0.1
        self.alpha = 1.0 # 0.7
        self.max_epochs = 100001
        self.eps = 0.1
        self.maxBatchSize = 64
        self.minCorpusSize = 200
        self.trainNumIter = 10

        self.debug = False
        self.walk = 50
        self.NUM_ACTIONS = 30
        self.FEATURES_PER_ACTION = 1

        self.saveDir = saveDir
        self.saveDirPlots = saveDirPlots

        self.deleteDuplicateTransitions = deleteDuplicateTransitions

        self.reward = 100.0 #17.0
        self.cost = -1.0
        self.unusedActionCost = 0.0 #-555.0
        self.maxDocs = 9999999999

        langPairList = langPair.split(",")
        assert(len(langPairList) == 2)
        self.langIds = [languages.GetLang(langPairList[0]), languages.GetLang(langPairList[1])]
        #print("self.langs", self.langs)

######################################################################################
def NumParallelDocs(env, visited):
    ret = 0
    for urlId in visited:
        node = env.nodes[urlId]
        #print("node", node.Debug())

        if node.alignedNode is not None and node.alignedNode.urlId in visited:
            ret += 1

    return ret

######################################################################################
def dumb(env, maxDocs, params):
    ret = []
    todo = []
    todo.append(env.rootNode)

    visited = set()
    langsVisited = {}

    while len(todo) > 0 and len(visited) < maxDocs:
        node = todo.pop(0)
        #print("node", node.Debug())

        if node.urlId not in visited:
            visited.add(node.urlId)
            if node.lang not in langsVisited:
                langsVisited[node.lang] = 0
            langsVisited[node.lang] += 1
            if params.debug and len(visited) % 40 == 0:
                print("   langsVisited", langsVisited)

            for link in node.links:
                childNode = link.childNode
                #print("   ", childNode.Debug())
                todo.append(childNode)

            numParallelDocs = NumParallelDocs(env, visited)
            ret.append(numParallelDocs)

    return ret

######################################################################################
def randomCrawl(env, maxDocs, params):
    ret = []
    todo = []
    todo.append(env.rootNode)

    visited = set()
    langsVisited = {}

    while len(todo) > 0 and len(visited) < maxDocs:
        idx = np.random.randint(0, len(todo))
        node = todo.pop(idx)
        #print("node", node.Debug())

        if node.urlId not in visited:
            visited.add(node.urlId)
            if node.lang not in langsVisited:
                langsVisited[node.lang] = 0
            langsVisited[node.lang] += 1
            if params.debug and len(visited) % 40 == 0:
                print("   langsVisited", langsVisited)

            for link in node.links:
                childNode = link.childNode
                #print("   ", childNode.Debug())
                todo.append(childNode)

            numParallelDocs = NumParallelDocs(env, visited)
            ret.append(numParallelDocs)

    return ret

######################################################################################
def balanced(env, maxDocs, params):
    ret = []
    visited = set()
    langsVisited = {}
    langsTodo = {}

    startNode = env.nodes[sys.maxsize]
    #print("startNode", startNode.Debug())
    assert(len(startNode.links) == 1)
    link = next(iter(startNode.links))

    while link is not None and len(visited) < maxDocs:
        node = link.childNode
        if node.urlId not in visited:
            #print("node", node.Debug())
            visited.add(node.urlId)
            if node.lang not in langsVisited:
                langsVisited[node.lang] = 0
            langsVisited[node.lang] += 1
            if params.debug and len(visited) % 40 == 0:
                print("   langsVisited", langsVisited)

            for link in node.links:
                #print("   ", childNode.Debug())
                AddTodo(langsTodo, visited, link)

            numParallelDocs = NumParallelDocs(env, visited)
            ret.append(numParallelDocs)

        link = PopLink(langsTodo, langsVisited, params)

    return ret

def PopLink(langsTodo, langsVisited, params):
    sum = 0
    # any nodes left to do
    for links in langsTodo.values():
        sum += len(links)
    if sum == 0:
        return None
    del sum

    # sum of all nodes visited
    sumAll = 0
    sumRequired = 0
    for lang, count in langsVisited.items():
        sumAll += count
        if lang in params.langIds:
            sumRequired += count
    sumRequired += 0.001 #1
    #print("langsVisited", sumAll, sumRequired, langsVisited)

    probs = {}
    for lang in params.langIds:
        if lang in langsVisited:
            count = langsVisited[lang]
        else:
            count = 0
        #print("langsTodo", lang, nodes)
        prob = 1.0 - float(count) / float(sumRequired)
        probs[lang] = prob
    #print("   probs", probs)

    links = None
    rnd = np.random.rand(1)
    #print("rnd", rnd, len(probs))
    cumm = 0.0
    for lang, prob in probs.items():
        cumm += prob
        #print("prob", prob, cumm)
        if cumm > rnd[0]:
            if lang in langsTodo:
                links = langsTodo[lang]
            break

    if links is not None and len(links) > 0:
        link = links.pop(0)
    else:
        link = RandomLink(langsTodo)
    #print("   node", node.Debug())
    return link

def RandomLink(langsTodo):
    while True:
        idx = np.random.randint(0, len(langsTodo))
        langs = list(langsTodo.keys())
        lang = langs[idx]
        links = langsTodo[lang]
        #print("idx", idx, len(nodes))
        if len(links) > 0:
            return links.pop(0)
    raise Exception("shouldn't be here")

def AddTodo(langsTodo, visited, link):
    childNode = link.childNode

    if childNode.urlId in visited:
        return

    parentNode = link.parentNode
    parentLang = parentNode.lang

    if parentLang not in langsTodo:
        langsTodo[parentLang] = []
    langsTodo[parentLang].append(link)

######################################################################################
######################################################################################
class Qnets():
    def __init__(self, params, max_env_maxLangId):
        self.q = []
        self.q.append(Qnetwork(params, max_env_maxLangId))
        self.q.append(Qnetwork(params, max_env_maxLangId))

######################################################################################
class Corpus:
    def __init__(self, params, qn):
        self.params = params
        self.qn = qn
        self.transitions = []
        self.losses = []
        self.sumWeights = []

    def AddTransition(self, transition):
        if self.params.deleteDuplicateTransitions:
            for currTrans in self.transitions:
                if currTrans.currURLId == transition.currURLId and currTrans.nextURLId == transition.nextURLId:
                    return
            # completely new trans

        self.transitions.append(transition)

    def GetBatchWithoutDelete(self, maxBatchSize):
        batch = []

        size = len(self.transitions)
        for i in range(maxBatchSize):
            idx = np.random.randint(0, size)
            transition = self.transitions[idx]
            batch.append(transition)

        return batch

    def Train(self, sess, env, params):
        if len(self.transitions) >= params.minCorpusSize:
            #for transition in self.transitions:
            #    print(DebugTransition(transition))

            for i in range(params.trainNumIter):
                batch = self.GetBatchWithoutDelete(params.maxBatchSize)
                loss, sumWeight = self.UpdateQN(params, env, sess, batch)
                self.losses.append(loss)
                self.sumWeights.append(sumWeight)
            self.transitions.clear()

    def UpdateQN(self, params, env, sess, batch):
        batchSize = len(batch)
        #print("batchSize", batchSize)
        langRequested = np.empty([batchSize, 1], dtype=np.int)
        langIds = np.empty([batchSize, 2], dtype=np.int)
        langFeatures = np.empty([batchSize, env.maxLangId + 1])
        targetQ = np.empty([batchSize, 1])

        i = 0
        for transition in batch:
            #curr = transition.curr
            #next = transition.next

            langRequested[i, :] = transition.langRequested
            langIds[i, :] = transition.langIds
            langFeatures[i, :] = transition.langFeatures
            targetQ[i, :] = transition.targetQ

            i += 1

        #_, loss, sumWeight = sess.run([qn.updateModel, qn.loss, qn.sumWeight], feed_dict={qn.input: childIds, qn.nextQ: targetQ})
        TIMER.Start("UpdateQN.1")
        loss, sumWeight = self.qn.Update(sess, langRequested, langIds, langFeatures, targetQ)
        TIMER.Pause("UpdateQN.1")

        #print("loss", loss)
        return loss, sumWeight

######################################################################################
class Transition:
    def __init__(self, currURLId, nextURLId, langRequested, langIds, langFeatures, targetQ):
        self.currURLId = currURLId
        self.nextURLId = nextURLId
        self.langRequested = langRequested
        self.langIds = langIds
        self.langFeatures = langFeatures #np.array(langFeatures, copy=True)
        self.targetQ = targetQ

    def DebugTransition(self):
        ret = str(self.currURLId) + "->" + str(self.nextURLId)
        return ret

######################################################################################
class Candidates:
    def __init__(self, params, env):
        self.params = params
        self.env = env
        self.dict = {} # parent lang -> links[]

        #for langId in params.langIds:
        #    self.dict[langId] = []

    def copy(self):
        ret = Candidates(self.params, self.env)

        for key, value in self.dict.items():
            #print("key", key, value)
            ret.dict[key] = value.copy()

        return ret

    def AddLink(self, link):
        langId = link.parentNode.lang
        if langId not in self.dict:
            self.dict[langId] = []
        self.dict[langId].append(link)

    def AddLinks(self, node, visited, params):
        #print("   currNode", curr, currNode.Debug())
        newLinks = node.GetLinks(visited, params)

        for link in newLinks:
            self.AddLink(link)

    def Pop(self, action):
        links = self.dict[action]
        assert(len(links) > 0)

        idx = np.random.randint(0, len(links))
        link = links.pop(idx)

        # remove all links going to same node
        for otherLinks in self.dict.values():
            otherLinksCopy = otherLinks.copy()
            for otherLink in otherLinksCopy:
                if otherLink.childNode == link.childNode:
                    otherLinks.remove(otherLink)

        return link

    def HasLinks(self, action):
        if action in self.dict and len(self.dict[action]) > 0:
            return True
        else:
            return False

    def Debug(self):
        ret = ""
        for lang in self.dict:
            ret += "lang=" + str(lang) + ":" + str(len(self.dict[lang])) + " "
            #links = self.dict[lang]
            #for link in links:
            #    ret += " " + link.parentNode.url + "->" + link.childNode.url
        return ret

######################################################################################
class Qnetwork():
    def __init__(self, params, max_env_maxLangId):
        self.params = params
        self.corpus = Corpus(params, self)

        HIDDEN_DIM = 512


        NUM_FEATURES = max_env_maxLangId + 1
        print('NUM_FEATURES', NUM_FEATURES)

        self.langRequested = tf.placeholder(shape=[None, 1], dtype=tf.float32)
        self.langIds = tf.placeholder(shape=[None, 2], dtype=tf.float32)
        self.langsVisited = tf.placeholder(shape=[None, NUM_FEATURES], dtype=tf.float32)
        self.input = tf.concat([self.langRequested, self.langIds, self.langsVisited], 1)
        #print("self.input", self.input.shape)

        self.W1 = tf.Variable(tf.random_uniform([NUM_FEATURES + 3, HIDDEN_DIM], 0, 0.01))
        self.b1 = tf.Variable(tf.random_uniform([1, HIDDEN_DIM], 0, 0.01))
        self.hidden1 = tf.matmul(self.input, self.W1)
        self.hidden1 = tf.add(self.hidden1, self.b1)
        self.hidden1 = tf.nn.relu(self.hidden1)
        #print("self.hidden1", self.hidden1.shape)

        self.W2 = tf.Variable(tf.random_uniform([HIDDEN_DIM, HIDDEN_DIM], 0, 0.01))
        self.b2 = tf.Variable(tf.random_uniform([1, HIDDEN_DIM], 0, 0.01))
        self.hidden2 = tf.matmul(self.hidden1, self.W2)
        self.hidden2 = tf.add(self.hidden2, self.b2)
        self.hidden2 = tf.nn.relu(self.hidden2)
        #print("self.hidden2", self.hidden2.shape)

        self.W3 = tf.Variable(tf.random_uniform([HIDDEN_DIM, HIDDEN_DIM], 0, 0.01))
        self.b3 = tf.Variable(tf.random_uniform([1, HIDDEN_DIM], 0, 0.01))
        self.hidden3 = tf.matmul(self.hidden2, self.W3)
        self.hidden3 = tf.add(self.hidden3, self.b3)
        self.hidden3 = tf.nn.relu(self.hidden3)
        #print("self.hidden3", self.hidden3.shape)

        self.hidden3 = tf.math.reduce_sum(self.hidden3, axis=1)
        self.qValue = self.hidden3
        #print("self.qValue", self.qValue.shape)

        self.sumWeight = tf.reduce_sum(self.W1) \
                         + tf.reduce_sum(self.b1) \
                         + tf.reduce_sum(self.W2) \
                         + tf.reduce_sum(self.b2) \
                         + tf.reduce_sum(self.W3) \
                         + tf.reduce_sum(self.b3)

        # Below we obtain the loss by taking the sum of squares difference between the target and prediction Q values.
        self.nextQ = tf.placeholder(shape=[None, 1], dtype=tf.float32)
        self.loss = tf.reduce_sum(tf.square(self.nextQ - self.qValue))
        #self.trainer = tf.train.GradientDescentOptimizer(learning_rate=lrn_rate)
        self.trainer = tf.train.AdamOptimizer() #learning_rate=lrn_rate)

        self.updateModel = self.trainer.minimize(self.loss)

    def Predict(self, sess, langRequested, langIds, langsVisited):
        langRequestedNP = np.empty([1,1])
        langRequestedNP[0,0] = langRequested

        langIdsNP = np.empty([1, 2])
        langIdsNP[0,0] = langIds[0]
        langIdsNP[0,1] = langIds[1]

        #print("input", langRequestedNP.shape, langIdsNP.shape, langFeatures.shape)
        #print("   ", langRequestedNP, langIdsNP, langFeatures)
        #print("numURLs", numURLs)
        qValue = sess.run([self.qValue],
                                feed_dict={self.langRequested: langRequestedNP,
                                    self.langIds: langIdsNP,
                                    self.langsVisited: langsVisited})
        qValue = qValue[0]
        #print("   qValue", qValue.shape, qValue)

        return qValue

    def PredictAll(self, env, sess, langIds, langsVisited, candidates):
        qValues = {}
        maxQ = -9999999.0

        for langId, nodes in candidates.dict.items():
            if len(nodes) > 0:
                qValue = self.Predict(sess, langId, langIds, langsVisited)
                qValue = qValue[0]
                qValues[langId] = qValue

                if maxQ < qValue:
                    maxQ = qValue
                    argMax = langId
        #print("qValues", env.maxLangId, qValues)

        if len(qValues) == 0:
            #print("empty qValues")
            qValues[0] = 0.0
            maxQ = 0.0
            argMax = 0

        return qValues, maxQ, argMax

    def Update(self, sess, langRequested, langIds, langsVisited, targetQ):
        #print("input", langRequested.shape, langIds.shape, langFeatures.shape, targetQ.shape)
        #print("   ", langRequested, langIds, langFeatures, targetQ)
        _, loss, sumWeight = sess.run([self.updateModel, self.loss, self.sumWeight],
                                    feed_dict={self.langRequested: langRequested,
                                            self.langIds: langIds,
                                            self.langsVisited: langsVisited,
                                            self.nextQ: targetQ})
        #print("loss", loss)
        return loss, sumWeight

######################################################################################
def GetNextState(env, params, action, visited, candidates):
    #print("candidates", action, candidates.Debug())
    if action == 0:
        # no explicit stop state but no candidates
        stopNode = env.nodes[0]
        link = Link("", 0, stopNode, stopNode)
    else:
        assert(candidates.HasLinks(action))
        link = candidates.Pop(action)

    assert(link is not None)
    nextNode = link.childNode
    #print("   nextNode", nextNode.Debug())

    if nextNode.urlId == 0:
        #print("   stop")
        reward = 0.0
    elif nextNode.alignedNode is not None and nextNode.alignedNode.urlId in visited:
        reward = params.reward
        #print("   visited", visited)
        #print("   reward", reward)
        #print()
    else:
        #print("   non-rewarding")
        reward = params.cost

    return link, reward

def NeuralWalk(env, params, eps, candidates, visited, langsVisited, sess, qnA):
    qValues, maxQ, action = qnA.PredictAll(env, sess, params.langIds, langsVisited, candidates)

    if np.random.rand(1) < eps:
        actions = list(qValues.keys())
        #print("actions", type(actions), actions)
        action = np.random.choice(actions)
        maxQ = qValues[action]
        #print("random")
    #print("action", action, qValues)

    #print("action", action, maxQ, qValues)
    link, reward = GetNextState(env, params, action, visited, candidates)
    assert(link is not None)
    #print("action", action, qValues, link.childNode.Debug(), reward)

    return qValues, maxQ, action, link, reward

def Neural(env, params, candidates, visited, langsVisited, sess, qnA, qnB):
    _, maxQ, action, link, reward = NeuralWalk(env, params, params.eps, candidates, visited, langsVisited, sess, qnA)
    assert(link is not None)
    #print("action", action, qValues, link, reward)

    # calc nextMaxQ
    nextVisited = visited.copy()
    nextVisited.add(link.childNode.urlId)

    nextCandidates = candidates.copy()
    nextCandidates.AddLinks(link.childNode, nextVisited, params)

    nextLangsVisited = langsVisited.copy()
    nextLangsVisited[0, link.childNode.lang] += 1

    _, _, nextAction = qnA.PredictAll(env, sess, params.langIds, nextLangsVisited, nextCandidates)
    nextMaxQ = qnB.Predict(sess, nextAction, params.langIds, nextLangsVisited)

    newVal = reward + params.gamma * nextMaxQ
    targetQ = (1 - params.alpha) * maxQ + params.alpha * newVal

    transition = Transition(link.parentNode.urlId,
                            link.childNode.urlId,
                            action,
                            params.langIds,
                            langsVisited,
                            targetQ)

    return transition

######################################################################################
def Trajectory(env, epoch, params, sess, qns):
    ret = []
    visited = set()
    langsVisited = np.zeros([1, env.maxLangId + 1]) # langId -> count
    candidates = Candidates(params, env)
    node = env.nodes[sys.maxsize]

    #stopNode = env.nodes[0]
    #link = Link("", 0, stopNode, stopNode)
    #candidates.AddLink(link)

    while True:
        tmp = np.random.rand(1)
        if tmp > 0.5:
            qnA = qns.q[0]
            qnB = qns.q[1]
        else:
            qnA = qns.q[1]
            qnB = qns.q[0]

        assert(node.urlId not in visited)
        #print("node", node.Debug())
        visited.add(node.urlId)
        langsVisited[0, node.lang] += 1
        #print("   langsVisited", langsVisited)

        candidates.AddLinks(node, visited, params)

        numParallelDocs = NumParallelDocs(env, visited)
        ret.append(numParallelDocs)

        transition = Neural(env, params, candidates, visited, langsVisited, sess, qnA, qnB)

        if transition.nextURLId == 0:
            break
        else:
            qnA.corpus.AddTransition(transition)
            node = env.nodes[transition.nextURLId]

        if len(visited) > params.maxDocs:
            break

    return ret

######################################################################################
def Walk(env, params, sess, qns):
    ret = []
    visited = set()
    langsVisited = np.zeros([1, env.maxLangId + 1]) # langId -> count
    candidates = Candidates(params, env)
    node = env.nodes[sys.maxsize]

    #stopNode = env.nodes[0]
    #link = Link("", 0, stopNode, stopNode)
    #candidates.AddLink(link)

    mainStr = "nodes:" + str(node.urlId)
    rewardStr = "rewards:"

    i = 0
    numAligned = 0
    totReward = 0.0
    totDiscountedReward = 0.0
    discount = 1.0

    while True:
        qnA = qns.q[0]
        assert(node.urlId not in visited)
        #print("node", node.Debug())
        visited.add(node.urlId)
        langsVisited[0, node.lang] += 1
        #print("   langsVisited", langsVisited)

        candidates.AddLinks(node, visited, params)

        numParallelDocs = NumParallelDocs(env, visited)
        ret.append(numParallelDocs)

        #print("candidates", candidates.Debug())
        qValues, _, action, link, reward = NeuralWalk(env, params, 0.0, candidates, visited, langsVisited, sess, qnA)
        node = link.childNode
        print("action", action, qValues)

        totReward += reward
        totDiscountedReward += discount * reward

        mainStr += "->" + str(node.urlId)
        rewardStr += "->" + str(reward)

        if node.alignedNode is not None:
            mainStr += "*"
            numAligned += 1

        discount *= params.gamma
        i += 1

        if node.urlId == 0:
            break

        if len(visited) > params.maxDocs:
            break

    mainStr += " " + str(i)
    rewardStr += " " + str(totReward) + "/" + str(totDiscountedReward)

    print(mainStr)
    print(rewardStr)
    return ret

######################################################################################
def Train(params, sess, saver, env, qns, env_test):
    totRewards = []
    totDiscountedRewards = []

    for epoch in range(params.max_epochs):
        print("epoch", epoch)
        TIMER.Start("Trajectory")
        _ = Trajectory(env, epoch, params, sess, qns)

        TIMER.Pause("Trajectory")

        TIMER.Start("Update")
        qns.q[0].corpus.Train(sess, env, params)
        qns.q[1].corpus.Train(sess, env, params)
        TIMER.Pause("Update")

        if epoch > 0 and epoch % params.walk == 0:
            arrDumb = dumb(env, len(env.nodes), params)
            arrRandom = randomCrawl(env, len(env.nodes), params)
            arrBalanced = balanced(env, len(env.nodes), params)
            arrRL = Walk(env, params, sess, qns)


            arrDumb_test = dumb(env_test, len(env_test.nodes), params)
            arrRandom_test = randomCrawl(env_test, len(env_test.nodes), params)
            arrBalanced_test = balanced(env_test, len(env_test.nodes), params)
            arrRL_test = Walk(env_test, params, sess, qns)

            print("epoch", epoch)

            fig = plt.figure()
            ax = fig.add_subplot(1,1,1)
            ax.plot(arrDumb, label="dumb_train", color='maroon')
            ax.plot(arrRandom, label="random_train", color='firebrick')
            ax.plot(arrBalanced, label="balanced_train", color='red')
            ax.plot(arrRL, label="RL_train", color='salmon')

            ax.legend(loc='upper left')
            plt.xlabel('#crawled')
            plt.ylabel('#found')

            fig.savefig("{}/{}_epoch{}.png".format(params.saveDirPlots, 'Train', epoch))
            #fig.show())

            #plt.pause(0.001)

            fig = plt.figure()
            ax = fig.add_subplot(1,1,1)
            ax.plot(arrDumb_test, label="dumb_test", color='navy')
            ax.plot(arrRandom_test, label="random_test", color='blue')
            ax.plot(arrBalanced_test, label="balanced_test", color='dodgerblue')
            ax.plot(arrRL_test, label="RL_test", color='lightskyblue')

            ax.legend(loc='upper left')
            plt.xlabel('#crawled')
            plt.ylabel('#found')
            fig.savefig("{}/{}_epoch{}".format(params.saveDirPlots, 'Test', epoch))

            #fig.show()

            #plt.pause(0.001)


    return totRewards, totDiscountedRewards

######################################################################################
def main():
    global TIMER
    TIMER = Timer()

    oparser = argparse.ArgumentParser(description="intelligent crawling with q-learning")
    oparser.add_argument("--config-file", dest="configFile", required=True,
                         help="Path to config file (containing MySQL login etc.)")
    oparser.add_argument("--language-pair", dest="langPair", required=True,
                         help="The 2 language we're interested in, separated by ,")
    oparser.add_argument("--save-dir", dest="saveDir", default=".",
                         help="Directory that model WIP are saved to. If existing model exists then load it")
    oparser.add_argument("--save-plots", dest="saveDirPlots", default="plot",
                     help="Directory ")
    oparser.add_argument("--delete-duplicate-transitions", dest="deleteDuplicateTransitions",
                         default=False, help="If True then only unique transition are used in each batch")
    options = oparser.parse_args()

    np.random.seed(99)
    np.set_printoptions(formatter={'float': lambda x: "{0:0.1f}".format(x)}, linewidth=666)

    sqlconn = MySQL(options.configFile)

    languages = Languages(sqlconn.mycursor)
    params = LearningParams(languages, options.saveDir, options.saveDirPlots, options.deleteDuplicateTransitions, options.langPair)

    #hostName = "http://vade-retro.fr/"
    hostName = "http://www.buchmann.ch/"
    hostName_test = "http://www.visitbritain.com/"
    env = Env(sqlconn, hostName)
    env_test = Env(sqlconn, hostName_test)
    # change language of start node. 0 = stop
    env.nodes[sys.maxsize].lang = languages.GetLang("None")
    env_test.nodes[sys.maxsize].lang = languages.GetLang("None")
    #for node in env.nodes.values():
    #    print(node.Debug())

    max_env_maxLangId = max([env.maxLangId, env_test.maxLangId])
    env.maxLangId = env_test.maxLangId = max_env_maxLangId

    tf.reset_default_graph()
    qns = Qnets(params, max_env_maxLangId)
    #qns_test = Qnets(params, env_test)
    init = tf.global_variables_initializer()

    saver = None #tf.train.Saver()
    os.mkdir(options.saveDirPlots)
    with tf.Session() as sess:
        sess.run(init)

        totRewards, totDiscountedRewards = Train(params, sess, saver, env, qns, env_test)

        #params.debug = True
        arrDumb = dumb(env, len(env.nodes), params)
        arrRandom = randomCrawl(env, len(env.nodes), params)
        arrBalanced = balanced(env, len(env.nodes), params)
        arrRL = Walk(env_test, params, sess, qns)
        #print("arrDumb", arrDumb)
        #print("arrBalanced", arrBalanced)

        plt.plot(arrDumb, label="dumb")
        plt.plot(arrRandom, label="random")
        plt.plot(arrBalanced, label="balanced")
        plt.plot(arrRL, label="RL")
        plt.legend(loc='upper left')
        plt.xlabel('#crawled')
        plt.ylabel('#found')
        plt.show()

######################################################################################
main()
