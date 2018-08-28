import re
from sys import argv
from shutil import copyfile
from os.path import dirname, basename, abspath
import yaml


def replaceTabs(doc, factor=2):
    """
    Replaces all tabs in doc with the given number of spaces.

    doc -- the string where tabs should be replaced 
    factor -- amount of spaces for one tab (default: 2)

    returns: the modified doc (doesn't change the original)
    """
    return doc.replace("\t", " "*factor)


class Line(object):
    """
    Represents a line of text.

    indent -- the indent (amount of spaces before text)
    next -- reference to the next line
    """
    def __init__(self, indent=0, next=None):
        self.indent = indent
        self.next = next


class EmptyLine(Line):
    """
    Represents an empty line.

    next -- see Line

    No indent.
    """
    def __init__(self, next=None):
        super(EmptyLine, self).__init__(next=next)

    def __str__(self):
        return ""

    def __repr__(self):
        return str(("[EmptyLine]"))
    

class CommentLine(Line):
    """
    Represents a line only containing a comment.

    indent -- see Line
    comment -- the text of the comment (without indent and "#")
    next -- see Line
    """
    def __init__(self, indent=0, comment=None, next=None):
        super(CommentLine, self).__init__(indent, next)
        self.comment = comment

    def __str__(self):
        return " " * self.indent + self.comment

    def __repr__(self):
        return str(("[CommentLine]", self.comment))


class CodeLine(Line):
    """
    Represents a line containing actual yaml "code".

    indent -- see Line
    key -- the part before the ":" or None if no ":" is present
    value -- the part after the ":" and before the first non-quoted "#" or None if empty
        If there is nothing after the ":" in this line but the next line is indented more, 
        value will not contain a string, but a list of CodeLines containing the nested lines.
    comment -- the part after the first non-quoted "#" or the empty string if no "#" is present
    parent -- the parent node (usually the first line above this one with lower indent) or None 
        for top-level nodes
    next -- see Line
    listDash -- whether this line starts with a dash (indicating that it is a list element)
        This is relevant for indentation, as list elements are on the same level as their parents

    key, value, and comment are stripped of leading and trailing whitespaces and don't include the 
    yaml separators ("-", ":", "#")
    """
    def __init__(self, indent=0, key=None, value=None, comment="", parent=None, next=None, listDash=False):
        super(CodeLine, self).__init__(indent, next)
        self.key = key
        self.value = value
        self.comment = comment
        self.parent = parent
        self.listDash = listDash

    def __str__(self):
        s = " " * self.indent
        if self.listDash:
            s += "- "
        if self.key:
            s += self.key + ": "
        if isinstance(self.value, basestring):
            s += self.value
        if self.comment:
            s += " # " + self.comment
        return s

    def __repr__(self):
        return str(("[CodeLine]", self.key, self.value, self.comment))

    def nextCodeLine(self):
        """Returns the next CodeLine after this one or None, if there is none."""
        line = self.next
        while (line is not None) and (not isinstance(line, CodeLine)):
            line = line.next
        return line

    def isParent(self, cl):
        """
        Returns whether self is a parent of cl, transitive relationships included.

        If another Line than a CodeLine is provided for cl, the result will be 
        returned for the next CodeLine found, following the .next pointers.
        If cl is None, False is returned.
        """
        while (cl is not None) and (not isinstance(cl, CodeLine)):
            cl = cl.next
        if cl is None:
            return False
        parent = cl.parent
        while parent is not None:
            if parent == self:
                return True
            else:
                parent = parent.parent
        return False


class Document(object):
    """
    Represents a yaml document as a list of Lines.

    The constructor parses the yaml string and turns it into the line representation.

    content -- a list of Lines representing the yaml file
    keyCache -- a cache for already computed keys.
        Maps lines to their corresponding yaml paths (in the form ".a.b.c").
    """

    def __init__(self, txt, tabsToSpaceFactor=2):
        """
        Transforms a yaml file into Line representation.

        txt -- the yaml
            This is supposed to be a string containing a yaml file. 
            It will be splitted by line breaks and then every line 
            is parsed into one of the subclasses of Line. 
            Check their documentation for further information.
        """
        # create cache for already computed keys
        self.keyCache = dict()

        # remove tabs and split for lines
        doc = replaceTabs(txt, tabsToSpaceFactor).split("\n")

        # convert string lines to Line type
        self.content = list()
        parentCodeLine = None
        lastLine = None
        multiline = -1
        for line in doc:
            match = re.search(r"\S", line) # match first non-whitespace character
            if match:
                indent = match.start()
                rawLine = line[indent:]
                if multiline >= 0:
                    # currently parsing a multiline string
                    if indent <= multiline:
                        # finished parsing the multiline string
                        multiline = -1
                    else:
                        # line is still part of multiline string
                        lastLine.value += "\n" + line
                        continue
                if match.group() == "#":
                    newLine = CommentLine(indent, rawLine)
                    self.content.append(newLine)
                else: # a line of yaml code
                    # check if a comment is appended
                    comment = ""
                    quotes = re.finditer(r"(\"|\').*?\1", rawLine) # extract quoted areas
                    quotePositions = list()
                    for q in quotes:
                        quotePositions.append((q.start(), q.end()))
                    commentPos = -1 # position of the '#' symbol or -1 if not found/only in quotes
                    comments = re.finditer("#", rawLine)
                    for c in comments:
                        commentPos = c.start() # position of the '#' symbol
                        for start, end in quotePositions:
                            if commentPos > start and commentPos < end:
                                # '#' symbol is within quotes
                                commentPos = -1 # mark symbol as irrelevant
                                break # check next symbol
                            elif commentPos < start:
                                # current quoted area is after the '#' symbol
                                break # unquoted '#' symbol has been found
                        if commentPos >= 0:
                            # unquoted '#' symbol has been found
                            break # stop checking '#' symbols
                    if commentPos>= 0:
                        comment = rawLine[commentPos + 1:].strip()
                        rawLine = rawLine[:commentPos]
                        
                    # check if line contains a "mapping"
                    mapping = re.search(":", rawLine) # won't work for : in keys
                    key = None
                    value = None
                    listDash = False
                    if mapping: # current line contains some kind of mapping
                        key = rawLine[:mapping.start()].strip()
                        if key[0] == "-":
                            key = key[1:].strip()
                            listDash = True
                        value = rawLine[mapping.start()+1:].strip()
                        value = value if len(value) > 0 else list()
                    else: # probably a simple list element
                        value = rawLine.strip()
                        if value[0] == "-":
                            value = value[1:].strip()
                            listDash = True
                    
                    # determine parent line
                    while parentCodeLine is not None:
                        # check if parentCodeLine is the "parent" of this code line
                        # => fewer indent determines this, but it is broken by the list element dash
                        # split condition over several ifs to improve readability
                        if parentCodeLine.indent < indent:
                            if (not parentCodeLine.listDash) or listDash:
                                break
                        elif parentCodeLine.indent == indent: 
                            if (not parentCodeLine.listDash) and listDash:
                                break
                        # current parentCodeLine is not parent, check its parent
                        parentCodeLine = parentCodeLine.parent

                    # determine multiline string
                    if isinstance(value, basestring) and (value[0] == r"|" or value[0] == r">"):
                        multiline = indent

                    # add to content
                    newLine = CodeLine(indent, key, value, comment, parentCodeLine, listDash=listDash)
                    if parentCodeLine is None: 
                        self.content.append(newLine)
                    else:
                        parentCodeLine.value.append(newLine)
                    parentCodeLine = newLine # set parentCodeLine to last line
            else: # no non-whitespace character on that line
                newLine = EmptyLine()
                self.content.append(newLine)

            # link line to previous line
            if lastLine is not None: # lastLine should only be None for the first line
                lastLine.next = newLine
            lastLine = newLine
        

    def __str__(self):
        s = ""
        for line in self:
            s += str(line) + "\n"
        return s[:-1] # cut off last line break


    class LineIterator(object):
        """An iterator for the Document class."""

        def __init__(self, start, filter=None):
            """
            Constructor for the LineIterator.

            start -- the first line from where to start iteration
                This is not necessarily the first Line to be returned, 
                the filter is also applied to this. 
            filter -- a subclass of Line
                Only Lines that are instances of that subclass will be returned.
            """
            self.current = start
            self.filter = filter
            if filter is not None:
                while (self.current is not None) and (not isinstance(self.current, self.filter)):
                    self.current = self.current.next

        def __iter__(self):
            return self
        
        def next(self):
            if self.current is None:
                raise StopIteration
            else:
                while (self.filter is not None) and (not isinstance(self.current, self.filter)):
                    self.current = self.current.next
                    if self.current is None:
                        raise StopIteration
                tmp = self.current
                self.current = self.current.next
                return tmp


    # returns an iterator over all lines
    def __iter__(self, filter=None):
        return self.LineIterator(self.content[0], filter)


    # human-readable alias for __iter__
    def iterate(self, filter=None):
        return self.__iter__(filter)


    def filterListByKeyPrefix(self, l, prefix):
        """
        Filters a list of Lines for a given yaml path prefix.

        l -- the list of Lines
        prefix -- the yaml path to be searched for

        This method is only used to retrieve Lines that are part of a yaml list
        and that list contains dictionaries. Dict entries in a list are not nested, 
        so returning all entries belonging to one list index requires to return 
        all lines that share a path prefix ending with that index - which is 
        exactly what this method does.

        The list is expected to be as it appears within the yaml file, so only 
        the first continuous sublist with all entries having the given prefix
        will be returned.
        """
        start = -1
        end = -1
        index = 0
        for e in l:
            if not isinstance(e, CodeLine):
                continue
            ekey = self.computeKey(e)
            if ekey[:len(prefix)] == prefix and (len(ekey) == len(prefix) or ekey[len(prefix)] == "."):
                if start < 0:
                    start = index
            else:
                if start >= 0:
                    end = index
                    break
            index += 1
        
        if start < 0:
            return None
        else:
            return l[start:] if end < 0 else l[start:end]


    def get(self, key, l=None):
        """
        Returns the line corresponding to the given yaml path. 

        key -- the yaml path
            The nested parts of the path are to be separated by ".", 
            a dot before the first part is optional. To access a list item, 
            specify it's index.
            Example: .a.1.c
                a:
                - x: y
                  z: x
                - b: 0
                  c: [points to this value] <<< this Line will be returned
        l -- the list of Lines to traverse
            This is only needed for recursion and will default to self.content.
            Just ignore it.
        """
        key = key if key[0] == "." else "." + key # add . to the beginning of key if not already there
        l = l if l is not None else self.content # default l to self.content
        for e in l:
            if not isinstance(e, CodeLine):
                continue
            ekey = self.computeKey(e)
            if ekey == key:
                return e
            elif key[:len(ekey)] == ekey and key[len(ekey)] == "." and isinstance(e.value, list):
                # ekey is prefix of key => go deeper
                return self.get(key, e.value)
            elif len(ekey) > len(key) and ekey[:len(key)] == key:
                # this will happen if the key ends with a
                # list index and that position contains a dict
                tmp = self.filterListByKeyPrefix(l, key)
                if tmp is None:
                    break
                return tmp
        raise KeyError("Key not found: {}".format(key))


    def computeKey(self, cl):
        """
        Computes the yaml path for a given CodeLine.

        cl -- the CodeLine

        The yaml path pointing to the value of this line is returned. 
        The different parts of the path are separated by ".", with a dot at 
        the beginning of the path. See documentation of the get method for 
        an example. 
        """
        if cl in self.keyCache: # check cache
            return self.keyCache[cl]

        # recursively determine key
        key = ""
        if cl.parent is not None: 
            key = self.computeKey(cl.parent)
            if key is None:
                # this would indicate that the parent has no key, 
                # which should never happen for a parent
                return None
            if isinstance(cl.parent.value, list) and cl.parent.value[0].listDash:
                # current line is part of a list => determine index
                index = -1
                for tmpLine in cl.parent.value:
                    if tmpLine.listDash:
                        index += 1
                    if tmpLine == cl:
                        break
                key += ".{}".format(index)
        
        key = key + ".{}".format(cl.key) if cl.key is not None else key
        self.keyCache[cl] = key
        return key


    def link(self, c):
        """
        Links Lines in a list or correctly.

        c -- a Line (may contain nested list)
        returns: the last Line contained in c (the one that needs to be linked to something outside of c)
        """
        if isinstance(c, Line):
            if isinstance(c.value, list):
                if len(c.value) > 0:
                    c.next = c.value[0]
                    old = self.link(c.next)
                    for e in c.value[1:]:
                        old.next = e
                        old = self.link(e)
                    return old
            return c # is returned if c doesn't contain a list or that list is empty
        else:
            raise TypeError("Invalid type for link: {}".format(type(c)))

    
    def mergeAnnotate(self, d):
        """
        Puts merge annotations into the document.

        d -- a dict mapping keys (see get function) to merge annotations (see merge function)
        returns: a list of warnings when keys weren't found

        This function will add the given annotations to the comment part of the lines 
        determined by the corresponding keys. All existing merge annotations in one of these 
        lines will be overwritten.
        """
        warnings = list()
        for key, value in d.iteritems():
            try:
                line = self.get(key)
                line.comment = line.comment.strip()
                while line.comment and line.comment[:6] == "[MERGE":
                    # overwrite merge annotation if it exists
                    line.comment = line.comment[line.comment.find("]") + 1:].strip()
                line.comment = (value + " " + line.comment).strip()
            except KeyError:
                warnings.append("Merge Annotation Warning: key '{}' for annotation '{}' not found!".format(key, value))
        return warnings



    def getKeys(self, l=None):
        """
        Returnes a list of yaml paths that are relevant for merging.

        l -- the list to traverse
            This is only needed for recursion. It defaults to self.content 
            and can/should be ignored.

        This returnes the leaves of a tree of keys (= yaml paths). It will return a 
        specific yaml path, if the value belonging to that key is 
            - a string
            - a list containing only strings and no mappings
            - marked with the [MERGE SUPER] annotation, see documentation of the 
                merge function for more information
        So yaml paths that contain nested mappings won't be returned. 
        Lists containing mappings as well as normal strings are not supported.
        """
        l = l if l is not None else self.content # default l to self.content
        res = dict()
        for e in l:
            if (not isinstance(e, CodeLine)) or (e.key is None):
                continue
            if e.comment[:12] == "[MERGE SUPER": # see documentation of merge function for info on merge annotations
                if e.comment[12] == "]":
                    e.comment = e.comment[13:].strip() # remove annotation
                    res[self.computeKey(e)] = e
                    continue # don't add subkeys in this case
                elif e.comment[12:18] == " LIST]":
                    if e.listDash and (e.key is not None): # [MERGE SUPER LIST] annotation only valid for beginning of list element mapping
                        ekey = self.computeKey(e)
                        ekey = ekey[:ekey.rfind(".")]
                        res[ekey] = e
            if e.value is None or isinstance(e.value, basestring):
                res[self.computeKey(e)] = e
            else:
                tmp = self.getKeys(e.value)
                if tmp:
                    res.update(tmp)
                else:
                    res[self.computeKey(e)] = e
        return res


def merge(dold, dnew, mergeAnnotations=None):
    """
    Merges two Documents, putting the values from the old one into the new one.

    === Parameters and Return Values ===

    dold -- the old Document
    dnew -- the new Document
        This will be modified to contain the merged content.
    mergeAnnotations (default: None) -- a dict mapping keys (same format as for get and getKeys functions)
        to merge annotations. The lines corresponding to the keys will get annotated with the specified 
        merge annotations prior to merging. This will overwrite all merge annotations on these lines 
        in dnew.
    
    This function extracts all relevant keys from dnew using the getKeys function. 
    Then every value for these keys is replaced with the value for this key from 
    dold. 

    returns: warnings, errors
    Both are lists of Lines where the corresponding value couldn't be found in dold. 
    This is considered an ERROR if:
        - dnew doesn't have a value either
        - dnew has a string as value, but that string starts with < (also with " or ' in front of it)
            In this case, the value is assumed to be a dummy value instead of a default value
    If a line has a list (size > 0) or a string starting with something else, it is assumed to be 
    a default value and will be returned as WARNING.

    === Merge Annotations ===

    Merge annotations always have the form "[MERGE <annotation>]" and are written at the beginning of 
    a comment in a CodeLine.
    
    Two merge annotations will be added automatically:
    [MERGE CHECK] -- indicates a warning for that line
    [MERGE FAIL] -- indicates an error for that line

    These merge annotations can be added to dnew before the merge to modify the merge behavior:
    [MERGE IGNORE] -- this line will be ignored, its value won't be overwritten and dold won't be 
        searched for the key
    [MERGE FROM <key>] -- instead of searching in dold for the same key, the value from the 
        specified key will be used instead. Usual warning/error behavior applies if the key is not found.
    [MERGE INSTEAD <key>] -- similar to MERGE FROM, but this will copy key and value from the specified 
        key in dold. Will always cause an ERROR if the key is not found in dold. 
    [MERGE PREFIX <prefix>] -- prepends the value fetched from dold with prefix in dnew. Will only have an 
        effect if the key is actually found in dold and is a string.
    [MERGE SUPER] -- this annotation is expected next to a key that usually wouldn't be returned by the 
        getKeys function (e.g. because it contains a mapping). Instead of returning its subkeys, getKeys will
        return this key. Another merge annotation can be written after this one. Comments in between 
        yaml lines under a node with this annotation will be lost, comments at the beginning or end might 
        be moved.

    All merge annotations other than CHECK and FAIL will be removed from dnew.
    """

    warnings = list()
    errors = list()

    if isinstance(mergeAnnotations, dict):
        warnings.extend(dnew.mergeAnnotate(mergeAnnotations))

    # iterate over CodeLines in new yaml
    for key, n in dnew.getKeys().iteritems():
        prefix = None
        try:
            # evaluate merge annotations
            if n.comment and n.comment[:6] == "[MERGE":
                if n.comment[7:14] == "IGNORE]":
                    # delete merge annotation and continue
                    n.comment = n.comment[14:].strip()
                    continue
                elif n.comment[7:12] == "FROM ":
                    # set key to given key and remove annotation
                    pos = n.comment.find("]")
                    key = n.comment[12:pos]
                    n.comment = n.comment[pos + 1:].strip()
                elif n.comment[7:15] == "INSTEAD ":
                    pos = n.comment.find("]")
                    key = n.comment[15:pos]
                    n.comment = n.comment[pos + 1:].strip()
                    n.value = None # dirty hack: set value to None it will cause an ERROR if the key is not found
                    n.key = dold.get(key).key
                elif n.comment[7:14] == "PREFIX ":
                    pos = n.comment.find("]")
                    prefix = n.comment[14:pos]
                    n.comment = n.comment[pos + 1:].strip()


            v = dold.get(key) # old line

            # if the value of either n or v is a list with len > 0, 
            # the linking between the lines (.next) needs to be fixed.
            nnext = n.next
            if isinstance(n.value, list):
                if len(n.value) > 0:
                    while n.isParent(nnext): # CommentLine and EmptyLine are handled by isParent function
                        nnext = nnext.next 
            if isinstance(v.value, basestring):
                n.value = v.value # overtake value from old yaml
                if prefix:
                    n.value = prefix + n.value # prepend prefix if any
                n.next = nnext
            else: # v.value should be a list
                n.value = list(v.value) # overtake value from old yaml without changing old yaml
                dnew.link(n).next = nnext # link last element of copied list to next element from dnew
                
            if not n.comment:
                n.comment = v.comment # overtake old comment, if no new comment set
            while n.comment and n.comment[:6] == "[MERGE":
                # remove old merge annotation
                n.comment = n.comment[n.comment.find("]") + 1:].strip()
        except KeyError:
            if isinstance(n.value, basestring):
                if len(n.value) > 1 and (n.value[0] == "<" or n.value[0:2] == "\"<" or n.value[0:2] == "'<"):
                    # if the value written in dnew looks like a dummy
                    n.comment = "[MERGE FAIL] " + n.comment
                    errors.append(n)
                else:
                    # there is probably a default value
                    n.comment = "[MERGE CHECK] " + n.comment
                    warnings.append(n)
            elif not n.value:
                # no value / empty list is assumed wrong 
                n.comment = "[MERGE FAIL] " + n.comment
                errors.append(n)
            else:
                # there is probably a default value
                n.comment = "[MERGE CHECK] " + n.comment
                warnings.append(n)
    return (warnings, errors)


#=== main ===
# read arguments
pold = argv[1] # path to old yaml file
pnew = argv[2] # path to new yaml file
psave = argv[3] # path where the merged file will be put
mergeinfo = None
if len(argv) > 4:
    fmi = open(argv[4]) # mergeinfo file
    mergeinfo = yaml.load(fmi.read())
    fmi.close()

# create backup and store it next to final file
copyfile(pold, dirname(abspath(psave)) + "/" + basename(psave) + ".backup") 

# read files to merge
fold = open(pold)
fnew = open(pnew)
dold = Document(fold.read())
dnew = Document(fnew.read())
fold.close()
fnew.close()

# merge
warnings, errors = merge(dold, dnew, mergeinfo)

# write merge result
fsave = open(psave, "w")
fsave.write(str(dnew))
fsave.close()

# evaluate merge result
if warnings:
    print "WARNINGS: "
    for w in warnings:
        print dnew.computeKey(w) if isinstance(w, CodeLine) else w
    print ""
if errors:
    print "ERRORS: "
    for e in errors:
        dnew.computeKey(e) if isinstance(e, CodeLine) else e
    print ""
    exit(1)
exit(0)