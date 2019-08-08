#!/usr/bin/env python3

import argparse
import sys
import os
import numpy as np
import pylab as plt
import tensorflow as tf
import random
from collections import namedtuple
import time
import argparse
import pickle
import hashlib

from helpers import Env, Candidates, Transition
from common import Timer, MySQL


class LearningParams:
    def __init__(self, saveDir, deleteDuplicateTransitions):
        self.gamma = 0.999
        self.lrn_rate = 0.1
        self.alpha = 1.0 # 0.7
        self.max_epochs = 20001
        self.eps = 1 # 0.7
        self.maxBatchSize = 64
        self.minCorpusSize = 200
        self.trainNumIter = 10
        
        self.debug = False
        self.walk = 1000
        self.NUM_ACTIONS = 30
        self.FEATURES_PER_ACTION = 2

        self.saveDir = saveDir
        self.deleteDuplicateTransitions = deleteDuplicateTransitions
        
        self.reward = 17.0
        self.cost = -1.0
        self.unusedActionCost = 0.0 #-555.0
        
######################################################################################
class Qnetwork():
    def __init__(self, params, env):
        self.corpus = Corpus(params, self)

        # These lines establish the feed-forward part of the network used to choose actions
        INPUT_DIM = 20
        EMBED_DIM = INPUT_DIM * params.NUM_ACTIONS * params.FEATURES_PER_ACTION
        #print("INPUT_DIM", INPUT_DIM, EMBED_DIM)
        
        HIDDEN_DIM = 1024

        # EMBEDDINGS
        self.embeddings = tf.Variable(tf.random_uniform([env.maxLangId + 1, INPUT_DIM], 0, 0.01))
        #print("self.embeddings", self.embeddings)

        self.input = tf.placeholder(shape=[None, params.NUM_ACTIONS * params.FEATURES_PER_ACTION], dtype=tf.int32)
        #print("self.input", self.input)

        self.embedding = tf.nn.embedding_lookup(self.embeddings, self.input)
        self.embedding = tf.reshape(self.embedding, [tf.shape(self.input)[0], EMBED_DIM])

        # NUMBER OF SIBLINGS
        self.siblings = tf.placeholder(shape=[None, params.NUM_ACTIONS], dtype=tf.float32)

        # NUMBER OF NODES
        self.numNodes = tf.placeholder(shape=[None, 1], dtype=tf.float32)

        # number of possible action. <= NUM_ACTIONS
        self.numActions = tf.placeholder(shape=[None, 1], dtype=tf.float32)

        # HIDDEN 1
        self.hidden1 = tf.concat([self.embedding, self.siblings, self.numNodes, self.numActions], 1) 

        self.Whidden1 = tf.Variable(tf.random_uniform([EMBED_DIM + params.NUM_ACTIONS + 2, EMBED_DIM], 0, 0.01))
        self.hidden1 = tf.matmul(self.hidden1, self.Whidden1)

        self.BiasHidden1 = tf.Variable(tf.random_uniform([1, EMBED_DIM], 0, 0.01))
        self.hidden1 = tf.add(self.hidden1, self.BiasHidden1)

        self.hidden1 = tf.math.l2_normalize(self.hidden1, axis=1)
        #self.hidden1 = tf.nn.relu(self.hidden1)

        # HIDDEN 2
        self.hidden2 = self.hidden1

        self.Whidden2 = tf.Variable(tf.random_uniform([EMBED_DIM, HIDDEN_DIM], 0, 0.01))
        self.hidden2 = tf.matmul(self.hidden2, self.Whidden2)

        self.BiasHidden2 = tf.Variable(tf.random_uniform([1, HIDDEN_DIM], 0, 0.01))

        self.hidden2 = tf.add(self.hidden2, self.BiasHidden2)

        # OUTPUT
        self.Wout = tf.Variable(tf.random_uniform([HIDDEN_DIM, params.NUM_ACTIONS], 0, 0.01))

        self.Qout = tf.matmul(self.hidden2, self.Wout)

        self.predict = tf.argmax(self.Qout, 1)

        self.sumWeight = tf.reduce_sum(self.Wout) \
                        + tf.reduce_sum(self.BiasHidden2) \
                        + tf.reduce_sum(self.Whidden2) \
                        + tf.reduce_sum(self.Whidden1)

        # Below we obtain the loss by taking the sum of squares difference between the target and prediction Q values.
        self.nextQ = tf.placeholder(shape=[None, params.NUM_ACTIONS], dtype=tf.float32)
        self.loss = tf.reduce_sum(tf.square(self.nextQ - self.Qout))
        #self.trainer = tf.train.GradientDescentOptimizer(learning_rate=lrn_rate)
        self.trainer = tf.train.AdamOptimizer() #learning_rate=lrn_rate)
        
        self.updateModel = self.trainer.minimize(self.loss)

    def PrintQ(self, urlId, params, env, sess):
        #print("hh", urlId, env.nodes)
        visited = set()
        unvisited = Candidates()

        node = env.nodes[urlId]
        unvisited.AddLinks(env, node.urlId, visited, params)

        urlIds, numURLs, featuresNP, siblings, numNodes = unvisited.GetFeaturesNP(env, params, visited)
        #print("featuresNP", featuresNP)
        
        #action, allQ = sess.run([self.predict, self.Qout], feed_dict={self.input: childIds})
        action, allQ = self.Predict(sess, featuresNP, siblings, numNodes, numURLs)
        
        #print("   curr=", curr, "action=", action, "allQ=", allQ, childIds)
        numURLsScalar = int(numURLs[0,0])
        urlIdsTruncate = urlIds[0, 0:numURLsScalar]                

        print(urlId, node.url, action, numURLsScalar, urlIdsTruncate, allQ, featuresNP)

    def PrintAllQ(self, params, env, sess):
        print("State URL action unvisited  Q-values features")
        for node in env.nodes.values():
            urlId = node.urlId
            self.PrintQ(urlId, params, env, sess)

    def Predict(self, sess, input, siblings, numNodes, numURLs):
        #print("input",input.shape, siblings.shape, numNodes.shape)
        #print("numURLs", numURLs)
        action, allQ = sess.run([self.predict, self.Qout], 
                                feed_dict={self.input: input, 
                                        self.siblings: siblings, 
                                        self.numNodes: numNodes,
                                        self.numActions: numURLs})
        action = action[0]
        
        return action, allQ

    def Update(self, sess, input, siblings, numNodes, numURLs, targetQ):
        #print("numURLs", numURLs.shape)
        _, loss, sumWeight = sess.run([self.updateModel, self.loss, self.sumWeight], 
                                    feed_dict={self.input: input, 
                                            self.siblings: siblings, 
                                            self.numNodes: numNodes, 
                                            self.numActions: numURLs,
                                            self.nextQ: targetQ})
        return loss, sumWeight

######################################################################################
class Qnets():
    def __init__(self, params, env):
        self.q = []
        self.q.append(Qnetwork(params, env))
        self.q.append(Qnetwork(params, env))

######################################################################################
class Corpus:
    def __init__(self, params, qn):
        self.qn = qn
        self.transitions = []
        self.losses = []
        self.sumWeights = []

    def AddTransition(self, transition, deleteDuplicateTransitions):
        if deleteDuplicateTransitions:
            for currTrans in self.transitions:
                if currTrans.currURLId == transition.currURLId and currTrans.nextURLId == transition.nextURLId:
                    return
            # completely new trans
    
        self.transitions.append(transition)

    def AddPath(self, path, deleteDuplicateTransitions):
        for transition in path:
            self.AddTransition(transition, deleteDuplicateTransitions)


    def GetBatch(self, maxBatchSize):        
        batch = self.transitions[0:maxBatchSize]
        self.transitions = self.transitions[maxBatchSize:]

        return batch

    def GetBatchWithoutDelete(self, maxBatchSize):
        batch = []

        size = len(self.transitions)
        for i in range(maxBatchSize):
            idx = np.random.randint(0, size)
            transition = self.transitions[idx]
            batch.append(transition)

        return batch

    def GetStopFeaturesNP(self, params):
        features = np.zeros([1, params.NUM_ACTIONS])
        return features

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
        features = np.empty([batchSize, params.NUM_ACTIONS * params.FEATURES_PER_ACTION], dtype=np.int)
        siblings = np.empty([batchSize, params.NUM_ACTIONS], dtype=np.int)
        targetQ = np.empty([batchSize, params.NUM_ACTIONS])
        numNodes = np.empty([batchSize, 1])
        numURLs = np.empty([batchSize, 1])

        i = 0
        for transition in batch:
            #curr = transition.curr
            #next = transition.next

            features[i, :] = transition.features
            targetQ[i, :] = transition.targetQ
            siblings[i, :] = transition.siblings
            numNodes[i, :] = transition.numNodes
            numURLs[i, :] = transition.numURLs

            i += 1

        #_, loss, sumWeight = sess.run([qn.updateModel, qn.loss, qn.sumWeight], feed_dict={qn.input: childIds, qn.nextQ: targetQ})
        TIMER.Start("UpdateQN.1")
        loss, sumWeight = self.qn.Update(sess, features, siblings, numNodes, numURLs, targetQ)
        TIMER.Pause("UpdateQN.1")

        #print("loss", loss)
        return loss, sumWeight


######################################################################################
def Neural(env, epoch, currURLId, params, sess, qnA, qnB, visited, unvisited, docsVisited):
    TIMER.Start("Neural.1")
    #DEBUG = False

    unvisited.AddLinks(env, currURLId, visited, params)
    urlIds, numURLs, featuresNP, siblings, numNodes = unvisited.GetFeaturesNP(env, params, visited)
    #print("   childIds", childIds, unvisited)
    TIMER.Pause("Neural.1")

    TIMER.Start("Neural.2")
    action, Qs = qnA.Predict(sess, featuresNP, siblings, numNodes, numURLs)
    
    if currURLId == sys.maxsize:
        action = 1
    elif np.random.rand(1) < params.eps:
        #if DEBUG: print("   random")
        action = np.random.randint(0, params.NUM_ACTIONS)
    TIMER.Pause("Neural.2")
    
    TIMER.Start("Neural.3")
    nextURLId, r = env.GetNextState(params, action, visited, urlIds)
    nextNode = env.nodes[nextURLId]
    #if DEBUG: print("   action", action, next, Qs)
    TIMER.Pause("Neural.3")

    TIMER.Start("Neural.4")
    visited.add(nextURLId)
    unvisited.RemoveLink(nextURLId)
    nextUnvisited = unvisited.copy()
    TIMER.Pause("Neural.4")

    TIMER.Start("Neural.5")
    if nextURLId == 0:
        done = True
        maxNextQ = 0.0
    else:
        assert(nextURLId != 0)
        done = False

        # Obtain the Q' values by feeding the new state through our network
        nextUnvisited.AddLinks(env, nextNode.urlId, visited, params)
        _, nextNumURLs, nextFeaturesNP, nextSiblings, nextNumNodes = nextUnvisited.GetFeaturesNP(env, params, visited)
        nextAction, nextQs = qnA.Predict(sess, nextFeaturesNP, nextSiblings, nextNumNodes, nextNumURLs)        
        #print("nextNumNodes", numNodes, nextNumNodes)
        #print("  nextAction", nextAction, nextQ)

        #assert(qnB == None)
        #maxNextQ = np.max(nextQs)

        _, nextQsB = qnB.Predict(sess, nextFeaturesNP, nextSiblings, nextNumNodes, nextNumURLs)
        maxNextQ = nextQsB[0, nextAction]
    TIMER.Pause("Neural.5")
        
    TIMER.Start("Neural.6")
    targetQ = Qs
    #targetQ = np.array(Qs, copy=True)
    #print("  targetQ", targetQ)
    newVal = r + params.gamma * maxNextQ
    targetQ[0, action] = (1 - params.alpha) * targetQ[0, action] + params.alpha * newVal
    #targetQ[0, action] = newVal
    ZeroOutStop(targetQ, urlIds, numURLs, params.unusedActionCost)

    #if DEBUG: print("   nextStates", nextStates)
    #if DEBUG: print("   targetQ", targetQ)

    transition = Transition(currURLId, 
                            nextNode.urlId, 
                            done, 
                            np.array(featuresNP, copy=True), 
                            np.array(siblings, copy=True), 
                            numNodes,
                            numURLs,
                            np.array(targetQ, copy=True))
    TIMER.Pause("Neural.6")

    return transition

######################################################################################
def ZeroOutStop(targetQ, urlIds, numURLs, unusedActionCost):
    #print("urlIds", numURLs, targetQ, urlIds)
    assert(targetQ.shape == urlIds.shape)
    targetQ[0,0] = 0.0
    
    #i = 0
    #for i in range(urlIds.shape[1]):
    #    if urlIds[0, i] == 0:
    #        targetQ[0, i] = 0

    numURLsScalar = int(numURLs[0,0])
    for i in range(numURLsScalar, targetQ.shape[1]):
        targetQ[0, i] = unusedActionCost

    #print("targetQ", targetQ)

######################################################################################
def Trajectory(env, epoch, currURLId, params, sess, qns):
    visited = set()
    unvisited = Candidates()
    docsVisited = set()

    while (True):
        tmp = np.random.rand(1)
        if tmp > 0.5:
            qnA = qns.q[0]
            qnB = qns.q[1]
        else:
            qnA = qns.q[1]
            qnB = qns.q[0]
        #qnA = qns.q[0]
        #qnB = None

        transition = Neural(env, epoch, currURLId, params, sess, qnA, qnB, visited, unvisited, docsVisited)
        
        qnA.corpus.AddTransition(transition, params.deleteDuplicateTransitions)

        currURLId = transition.nextURLId
        #print("visited", visited)

        if transition.done: break
    #print("unvisited", unvisited)


######################################################################################
def Train(params, sess, saver, env, qns):
    totRewards = []
    totDiscountedRewards = []

    for epoch in range(params.max_epochs):
        #print("epoch", epoch)
        #startState = 30
        
        TIMER.Start("Trajectory")
        Trajectory(env, epoch, sys.maxsize, params, sess, qns)
        TIMER.Pause("Trajectory")

        TIMER.Start("Update")
        qns.q[0].corpus.Train(sess, env, params)
        qns.q[1].corpus.Train(sess, env, params)
        TIMER.Pause("Update")

        if epoch > 0 and epoch % params.walk == 0:
            if len(qns.q[0].corpus.losses) > 0:
                # trained at least once
                #qns.q[0].PrintAllQ(params, env, sess)
                qns.q[0].PrintQ(0, params, env, sess)
                qns.q[0].PrintQ(sys.maxsize, params, env, sess)
                print()

                numAligned, totReward, totDiscountedReward = env.Walk(sys.maxsize, params, sess, qns.q[0], True)
                totRewards.append(totReward)
                totDiscountedRewards.append(totDiscountedReward)
                print("epoch", epoch, "loss", qns.q[0].corpus.losses[-1], "eps", params.eps, "alpha", params.alpha)
                print()
                sys.stdout.flush()

                #saver.save(sess, "{}/hh".format(params.saveDir), global_step=epoch)

                #numAligned = env.GetNumberAligned(path)
                #print("path", numAligned, env.numAligned)
                if numAligned >= env.numAligned - 5:
                    #print("got them all!")
                    #eps = 1. / ((i/50) + 10)
                    params.eps *= .99
                    params.eps = max(0.1, params.eps)
                    
                    #params.alpha *= 0.99
                    #params.alpha = max(0.3, params.alpha)
                
            #print("epoch", epoch, \
            #     len(qns.q[0].corpus.transitions), len(qns.q[1].corpus.transitions)) #, \
            #     #DebugTransitions(qns.q[0].corpus.transitions))
                

    return totRewards, totDiscountedRewards
            
def DebugTransitions(transitions):
    ret = ""
    for transition in transitions:
        str = transition.Debug()
        ret += str + " "
    return ret

######################################################################################

def Main():
    print("Starting")
    global TIMER
    TIMER = Timer()

    oparser = argparse.ArgumentParser(description="intelligent crawling with q-learning")
    oparser.add_argument("--config-file", dest="configFile", required=True,
                         help="Path to config file (containing MySQL login etc.")
    oparser.add_argument("--save-dir", dest="saveDir", default=".",
                     help="Directory that model WIP are saved to. If existing model exists then load it")
    oparser.add_argument("--delete-duplicate-transitions", dest="deleteDuplicateTransitions", default=False,
                     help="If True then only unique transition are used in each batch")
    options = oparser.parse_args()

    np.random.seed()
    np.set_printoptions(formatter={'float': lambda x: "{0:0.1f}".format(x)}, linewidth=666)

    sqlconn = MySQL(options.configFile)

    hostName = "http://vade-retro.fr/"
    #hostName = "http://www.buchmann.ch/"
    #hostName = "http://www.visitbritain.com/"
    #pickleName = hostName + ".pickle"

    env = Env(sqlconn, hostName)
    # if os.path.exists(pickleName):
    #     with open(pickleName, 'rb') as f:
    #         print("unpickling")
    #         env = pickle.load(f)
    # else:
    #     env = Env(sqlconn, hostName)
    #     with open(pickleName, 'wb') as f:
    #         print("pickling")
    #         pickle.dump(env,f)
        

    params = LearningParams(options.saveDir, options.deleteDuplicateTransitions)

    tf.reset_default_graph()
    qns = Qnets(params, env)
    init = tf.global_variables_initializer()

    saver = tf.train.Saver()
    with tf.Session() as sess:
    #with tf.Session(config=tf.ConfigProto(log_device_placement=True)) as sess:
        sess.run(init)

        qns.q[0].PrintAllQ(params, env, sess)
        #env.WalkAll(params, sess, qn)
        print()

        TIMER.Start("Train")
        totRewards, totDiscountedRewards = Train(params, sess, saver, env, qns)
        TIMER.Pause("Train")
        
        #qn.PrintAllQ(params, env, sess)
        #env.WalkAll(params, sess, qn)

        env.Walk(sys.maxsize, params, sess, qns.q[0], True)

        del TIMER

        plt.plot(totRewards)
        plt.plot(totDiscountedRewards)
        plt.show()

        plt.plot(qns.q[0].corpus.losses)
        plt.plot(qns.q[1].corpus.losses)
        plt.show()

        plt.plot(qns.q[0].corpus.sumWeights)
        plt.plot(qns.q[1].corpus.sumWeights)
        plt.show()

    print("Finished")

if __name__ == "__main__":
    Main()
