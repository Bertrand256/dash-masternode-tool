## Browsing and voting on proposals

Version 0.9.8 of *DMT* introduced functionality for *masternode owners* (MNOs) to review and cast votes on current proposals. In addition to MNOs, this feature is also useful to *proposal owners*, who can use it to track and analyze voting progress on their proposals.


To use these features, open the *Proposals* window by clicking the `Proposals` buttom in the main application window or the `Tools->Proposals` menu item. The following window appears:  
![Proposals window](img/dmt-proposals-window.png)

The first time you open the window, it will take a few minutes for the application to retrieve data on all of the proposals currently maintained by the network, as well as the votes cast on them by masternodes. That data is saved to a cache database, so the opening the window should be faster once the data in in the local cache.

The upper part of the window shows a list of proposals in a table, with several common proposal attributes visible in columns. You can control visibility and the display order of the columns by clicking the `Columns` button and enabling or reordering the columns of interest to you in the `Columns` dialog.  
![Column selection dialog](img/dmt-proposals-columns.png)

In the `Proposals` dialog, you can:
 * View the list of all of the currently available proposals and associated details.
 * View the list of votes cast on particular proposal.
 * Cast a vote on proposals (if a masternode is configured in *DMT*).
 * Save proposal and vote data to a CSV file for further analysis.
 * View charts showing voting progress over time.
 * Filter proposals by its properties: name, title, proposal owner


### Reviewing proposal details

All key proposal details can be viewed on the `Details` tab in the lower section of the `Proposals` window (see screenshot above).

### Reviewing voting details

On the `Voting History` tab you can view:
 * A list of all votes, along with the vote timestamp and voting masternode.
 * An incremental chart of votes over time.
 * A chart of changed votes over time (MNOs can change their vote at any time during the voting period).
 * A chart summarizing YES, NO and ABSTAIN vote counts.  
    ![Voting history tab](img/dmt-proposals-voting-history.png)  

    Vote change chart:  
    ![Vote change chart](img/dmt-proposals-vote-change-chart.png)  

    Vote summary chart:  
    ![Vote summary chart](img/dmt-proposals-vote-summary-chart.png)

### Casting votes

In the main proposals list, select the proposal(s), you'd like to vote on.

> Note: from DMT v0.9.18 you can select and vote on multiple proposals

Open the `Vote` tab in the lower section of the `Proposals` window. You will see one row of voting buttons (*Yes*, *No*, *Abstain*) for each masternode registered in the application, and an additional row of buttons at the top to cast votes using all masternodes registered in the application:  
![Vote tab](img/dmt-proposals-vote.png)

Alternatively, you can vote on the `Details` tab, using the links from the topof the tab, but remember, that this option will not allow you to vote with a specific masternode - votes are cast on behalf of all masternodes you have in your configuration:  
![Vote tab](img/dmt-proposals-vote-2.png)

#### Privacy

If you own several masternodes, you should consider that casting a vote with all of them simultaneously is in effect publicly linking all of the nodes to a single owner, which may be considered a privacy risk. The following screenshot highlights this point:  
![Simultaneous voting](img/dmt-proposals-vote-time-offset.png)  
Bear in mind that all of this information is available to anybody with access to any Dash daemon.

Fortunately, there is an easy way to mitigate this type of timing attack. *DMT* can add a random offset (within a range of +/- 30 min) to the voting time for each of configured masternode, so clicking one of the `Yes/No/Abstain for all` buttons will result in a different voting timestamp for each masternode, as seen by the network. This feature can be enabled using the `Add random offset to new vote time to enhance privacy` option, as shown in the screenshot below:  
![Random offset for voting](img/dmt-proposals-config-time-offset.png)
